"""Webhook 事件中心（P6-T6.1，思想移植 creatorhub event_center）：outbox + HMAC 签名 + 重试。

流程：业务方调 emit() 写事件 → 后台每 15s 扫 pending 事件 → 按订阅过滤投递，
带 x-flowpulse-signature-256（HMAC-SHA256(secret, body)）→ 失败重试最多 5 次。
事件类型（当前接入）：monitor.new_works / risk.cooldown / download.completed。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.db.models import WebhookEventRow, WebhookSubscriptionRow

MAX_ATTEMPTS = 5
DISPATCH_INTERVAL_SECONDS = 15
BATCH_SIZE = 20

KNOWN_EVENT_TYPES = ("monitor.new_works", "risk.cooldown", "download.completed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EventCenter:
    def __init__(self, sessionmaker_: sessionmaker[Session] | None, json_dir: Path, client: httpx.AsyncClient):
        self._sessionmaker = sessionmaker_
        self._json_dir = json_dir
        self._json_dir.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._task: asyncio.Task | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.dispatch_pending()
            except Exception:  # noqa: BLE001 - 后台循环不允许中断
                pass
            await asyncio.sleep(DISPATCH_INTERVAL_SECONDS)

    # ---- 发射事件（业务方入口） ----

    def emit(self, event_type: str, title: str, payload: dict | None = None) -> int | None:
        """写一条 pending 事件，返回事件 id（无订阅者时跳过不写）。"""
        if not self.list_subscriptions(enabled_only=True):
            return None
        row = {
            "event_type": event_type,
            "title": title[:500],
            "payload": payload or {},
            "status": "pending",
            "attempts": 0,
        }
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                obj = WebhookEventRow(**row)
                session.add(obj)
                session.commit()
                session.refresh(obj)
                return obj.id
        data = read_json(self._events_path, {"events": [], "next_id": 1})
        row["id"] = data["next_id"]
        row["created_at"] = _now().isoformat(timespec="seconds")
        data["next_id"] += 1
        data["events"].insert(0, row)
        # 环形裁剪：只保留最近 500 条（含终态历史）
        data["events"] = data["events"][:500]
        atomic_write_json(self._events_path, data)
        return row["id"]

    # ---- 订阅管理 ----

    def list_subscriptions(self, enabled_only: bool = False) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                query = select(WebhookSubscriptionRow).order_by(WebhookSubscriptionRow.id)
                rows = session.execute(query).scalars().all()
                return [self._sub_to_dict(r) for r in rows if not enabled_only or r.enabled]
        data = read_json(self._subs_path, {"subscriptions": []})
        subs = [dict(s) for s in data.get("subscriptions", [])]
        return [s for s in subs if s.get("enabled", True)] if enabled_only else subs

    def upsert_subscription(self, url: str, secret: str = "", events: str = "", enabled: bool = True) -> dict:
        """按 URL 去重新增/更新订阅。events 逗号分隔事件类型过滤（空 = 全部）。"""
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"订阅地址无效：{url[:80]}")
        existing = next((s for s in self.list_subscriptions() if s["url"] == url), None)
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                if existing:
                    obj = session.get(WebhookSubscriptionRow, existing["id"])
                    obj.secret, obj.events, obj.enabled = secret, events, enabled
                else:
                    session.add(
                        WebhookSubscriptionRow(url=url, secret=secret, events=events, enabled=enabled)
                    )
                session.commit()
        else:
            data = read_json(self._subs_path, {"subscriptions": [], "next_id": 1})
            if existing:
                for s in data["subscriptions"]:
                    if s["url"] == url:
                        s.update(secret=secret, events=events, enabled=enabled)
            else:
                data["subscriptions"].append(
                    {"id": data.get("next_id", 1), "url": url, "secret": secret,
                     "events": events, "enabled": enabled,
                     "created_at": _now().isoformat(timespec="seconds")}
                )
                data["next_id"] = data.get("next_id", 1) + 1
            atomic_write_json(self._subs_path, data)
        return next(s for s in self.list_subscriptions() if s["url"] == url)

    def delete_subscription(self, sub_id: int) -> bool:
        if self._sessionmaker is not None:
            from sqlalchemy import delete as sa_delete

            with self._sessionmaker() as session:
                result = session.execute(
                    sa_delete(WebhookSubscriptionRow).where(WebhookSubscriptionRow.id == sub_id)
                )
                session.commit()
                return bool(result.rowcount)
        data = read_json(self._subs_path, {"subscriptions": []})
        before = len(data["subscriptions"])
        data["subscriptions"] = [s for s in data["subscriptions"] if s["id"] != sub_id]
        if len(data["subscriptions"]) == before:
            return False
        atomic_write_json(self._subs_path, data)
        return True

    # ---- 投递 ----

    def _load_pending(self) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = (
                    session.execute(
                        select(WebhookEventRow)
                        .where(WebhookEventRow.status == "pending")
                        .order_by(WebhookEventRow.id)
                        .limit(BATCH_SIZE)
                    )
                    .scalars()
                    .all()
                )
                return [self._event_to_dict(r) for r in rows]
        data = read_json(self._events_path, {"events": []})
        return [e for e in data["events"] if e["status"] == "pending"][:BATCH_SIZE]

    def _mark(self, event_id: int, status: str, attempts: int, detail: str = "") -> None:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                obj = session.get(WebhookEventRow, event_id)
                if obj:
                    obj.status, obj.attempts = status, attempts
                    obj.last_detail = detail[:500]
                    obj.last_attempt_at = _now()
                    session.commit()
        else:
            data = read_json(self._events_path, {"events": []})
            for e in data["events"]:
                if e["id"] == event_id:
                    e.update(status=status, attempts=attempts,
                             last_detail=detail[:500],
                             last_attempt_at=_now().isoformat(timespec="seconds"))
                    break
            atomic_write_json(self._events_path, data)

    @staticmethod
    def _matches(subscription: dict, event_type: str) -> bool:
        events = [e.strip() for e in (subscription.get("events") or "").split(",") if e.strip()]
        return not events or event_type in events

    async def _deliver(self, subscription: dict, event: dict) -> tuple[bool, str]:
        body = json.dumps(
            {
                "event": event["event_type"],
                "title": event["title"],
                "payload": event.get("payload") or {},
                "timestamp": int(time.time()),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        secret = subscription.get("secret") or ""
        if secret:
            signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["x-flowpulse-signature-256"] = f"sha256={signature}"
        try:
            response = await self._client.post(subscription["url"], content=body, headers=headers, timeout=10)
            ok = 200 <= response.status_code < 300
            return ok, "" if ok else f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            return False, str(exc)[:120]

    async def dispatch_pending(self) -> dict:
        """把 pending 事件投给匹配订阅；全部送达 → delivered，否则按尝试次数决定。"""
        pending = self._load_pending()
        summary = {"dispatched": 0, "delivered": 0, "failed": 0}
        subscriptions = self.list_subscriptions(enabled_only=True)
        for event in pending:
            summary["dispatched"] += 1
            targets = [s for s in subscriptions if self._matches(s, event["event_type"])]
            if not targets:
                self._mark(event["id"], "failed", event.get("attempts", 0), "无匹配订阅")
                summary["failed"] += 1
                continue
            results = [await self._deliver(s, event) for s in targets]
            attempts = int(event.get("attempts", 0)) + 1
            if all(ok for ok, _ in results):
                self._mark(event["id"], "delivered", attempts)
                summary["delivered"] += 1
            elif attempts >= MAX_ATTEMPTS:
                self._mark(event["id"], "failed", attempts, "; ".join(d for _, d in results if d)[:500])
                summary["failed"] += 1
            else:
                # 部分成功仍算 partial，继续重试剩余渠道
                self._mark(event["id"], "partial" if any(ok for ok, _ in results) else "pending", attempts,
                           "; ".join(d for _, d in results if d)[:500])
        return summary

    def list_events(self, limit: int = 50) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = (
                    session.execute(
                        select(WebhookEventRow).order_by(WebhookEventRow.id.desc()).limit(limit)
                    )
                    .scalars()
                    .all()
                )
                return [self._event_to_dict(r) for r in rows]
        data = read_json(self._events_path, {"events": []})
        return data["events"][:limit]

    @property
    def _events_path(self) -> Path:
        return self._json_dir / "webhook_events.json"

    @property
    def _subs_path(self) -> Path:
        return self._json_dir / "webhook_subscriptions.json"

    @staticmethod
    def _event_to_dict(row: WebhookEventRow) -> dict:
        return {
            "id": row.id, "event_type": row.event_type, "title": row.title,
            "payload": row.payload or {}, "status": row.status, "attempts": row.attempts,
            "last_detail": row.last_detail,
            "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _sub_to_dict(row: WebhookSubscriptionRow) -> dict:
        return {
            "id": row.id, "url": row.url, "secret": row.secret,
            "events": row.events, "enabled": row.enabled,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


# router 导出放末尾（routes 依赖本模块的 EventCenter，需延迟导入避免循环）
from flowpulse.modules.events.routes import get_event_center, router  # noqa: E402,F401
