"""通知渠道模块：页面管理 webhook 渠道 + 发送记录（数据库/文件双模式存储）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.config import get_settings
from flowpulse.core.notify import WebhookNotifier
from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.db.models import NotifyChannelRow, NotifyLogRow

router = APIRouter()

# 发送记录保留条数（DB 与 JSON 模式一致裁剪）
_LOG_KEEP = 200


class ChannelIn(BaseModel):
    name: str = Field(default="", max_length=64)
    url: str = Field(min_length=1, max_length=500)
    enabled: bool = True


class ChannelsUpdateRequest(BaseModel):
    channels: list[ChannelIn]


class NotifyStore:
    """渠道与日志存储：DATABASE_URL 模式走 fp_notify_channels/fp_notify_logs，
    否则 data/notify/{channels,logs}.json。"""

    def __init__(self, sessionmaker_: sessionmaker[Session] | None, json_dir: Path):
        self._sessionmaker = sessionmaker_
        self._json_dir = json_dir
        self._json_dir.mkdir(parents=True, exist_ok=True)

    # ---- 渠道 ----

    def list_channels(self) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = session.execute(
                    select(NotifyChannelRow).order_by(NotifyChannelRow.id)
                ).scalars().all()
                return [
                    {"id": row.id, "name": row.name, "url": row.url, "enabled": row.enabled}
                    for row in rows
                ]
        data = read_json(self._channels_path, {})
        return [dict(item) for item in data.get("channels", [])]

    def list_enabled_urls(self) -> list[str]:
        return [c["url"] for c in self.list_channels() if c.get("enabled", True)]

    def replace_channels(self, items: list[dict]) -> list[dict]:
        normalized = []
        for index, item in enumerate(items):
            url = (item.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"第 {index + 1} 条渠道地址无效：{url[:80]}")
            normalized.append(
                {
                    "name": (item.get("name") or "").strip() or f"渠道{index + 1}",
                    "url": url,
                    "enabled": bool(item.get("enabled", True)),
                }
            )
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                session.execute(sa_delete(NotifyChannelRow))
                session.add_all([NotifyChannelRow(**c) for c in normalized])
                session.commit()
        else:
            atomic_write_json(self._channels_path, {"channels": normalized})
        return self.list_channels()

    # ---- 日志 ----

    def add_log(self, channel: str, kind: str, title: str, ok: bool, detail: str = "") -> None:
        if self._sessionmaker is not None:
            from datetime import UTC, datetime

            with self._sessionmaker() as session:
                session.add(
                    NotifyLogRow(
                        channel=channel, kind=kind, title=title,
                        ok=ok, detail=detail, created_at=datetime.now(UTC),
                    )
                )
                session.commit()
                # 环形裁剪：只保留最近 _LOG_KEEP 条
                keep_ids = session.execute(
                    select(NotifyLogRow.id).order_by(
                        NotifyLogRow.id.desc()
                    ).limit(_LOG_KEEP)
                ).scalars().all()
                if keep_ids:
                    session.execute(
                        sa_delete(NotifyLogRow).where(NotifyLogRow.id.notin_(keep_ids))
                    )
                    session.commit()
        else:
            from flowpulse.modules.weread.models import now_iso

            entry = {
                "channel": channel, "kind": kind, "title": title,
                "ok": ok, "detail": detail, "created_at": now_iso(),
            }
            data = read_json(self._logs_path, {})
            logs = data.get("logs", [])
            logs.insert(0, entry)
            atomic_write_json(self._logs_path, {"logs": logs[:_LOG_KEEP]})

    def list_logs(self, limit: int = 50) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = session.execute(
                    select(NotifyLogRow).order_by(NotifyLogRow.id.desc()).limit(limit)
                ).scalars().all()
                return [
                    {
                        "channel": row.channel, "kind": row.kind, "title": row.title,
                        "ok": row.ok, "detail": row.detail,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ]
        data = read_json(self._logs_path, {})
        return data.get("logs", [])[:limit]

    @property
    def _channels_path(self) -> Path:
        return self._json_dir / "channels.json"

    @property
    def _logs_path(self) -> Path:
        return self._json_dir / "logs.json"


def get_notify_store() -> NotifyStore:
    raise RuntimeError("Dependency override is not configured")


def get_weread_notifier() -> WebhookNotifier:
    raise RuntimeError("Dependency override is not configured")


def _env_channels() -> list[dict]:
    settings = get_settings()
    raw = [settings.weread_webhook_url, settings.weread_notify_channels]
    urls: list[str] = []
    for chunk in raw:
        if not chunk:
            continue
        urls.extend(u.strip() for u in chunk.replace("，", ",").split(","))
    seen, result = set(), []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            kind = "飞书" if "open.feishu.cn" in url else "钉钉" if "oapi.dingtalk.com" in url else "自定义"
            result.append({"name": f"环境变量 · {kind}", "url": url, "enabled": True, "source": "env"})
    return result


@router.get("/api/notify/channels")
def list_channels(store: NotifyStore = Depends(get_notify_store)) -> dict:
    channels = [
        {**c, "source": "db"} for c in store.list_channels()
    ]
    return {"channels": _env_channels() + channels}


@router.put("/api/notify/channels")
def update_channels(
    request: ChannelsUpdateRequest, store: NotifyStore = Depends(get_notify_store)
) -> dict:
    try:
        store.replace_channels([c.model_dump() for c in request.channels])
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"channels": _env_channels() + [
        {**c, "source": "db"} for c in store.list_channels()
    ]}


@router.post("/api/notify/test")
async def test_send(
    notifier: WebhookNotifier = Depends(get_weread_notifier),
) -> dict:
    """向全部渠道发一条测试消息，并返回最近的发送记录。"""
    sent = await notifier.send(
        "notify:test", "心流 FlowPulse · 通知测试", "收到这条说明通知渠道配置正常 ✅",
        cooldown_seconds=0,
    )
    return {"sent": sent}


@router.get("/api/notify/logs")
def list_logs(
    limit: int = 50, store: NotifyStore = Depends(get_notify_store)
) -> dict:
    return {"logs": store.list_logs(min(limit, 200))}
