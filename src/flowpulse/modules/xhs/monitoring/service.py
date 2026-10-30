"""小红书作品监控服务：拉取 → 规范化 → 过滤 → 去重入库 → 新作品通知。

扫描语义（T1.2）：
- 首扫（last_scan_at 为空）：只入库 backfill_count 条基线，notified=True，不推送（防旧作品轰炸）；
- 增量扫：note_id 全局去重，新作品入库并推送一条汇总通知（最多列 5 条标题）；
- include/exclude 关键词按标题过滤（include 为空 = 全收，exclude 命中即弃）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flowpulse.core.notify import WebhookNotifier
from flowpulse.modules.xhs.integration.models import SearchRequest
from flowpulse.modules.xhs.monitoring.store import XhsMonitorRepository

# 单次扫描拉取上限（关键词搜索翻页量 / 创作者全量笔记的截断）
SCAN_LIMIT = 50


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_note(item: dict) -> dict | None:
    """把搜索 items（id + note_card）与用户笔记列表（note_id 顶层）两种形态规范化。

    返回 None 表示不是笔记项（搜索结果里的广告/用户卡片等）。
    """
    card = item.get("note_card") if isinstance(item.get("note_card"), dict) else item
    note_id = item.get("note_id") or item.get("id") or card.get("note_id")
    if not note_id or item.get("model_type") not in (None, "", "note"):
        return None
    user = card.get("user") or item.get("user") or {}
    interact = card.get("interact_info") or item.get("interact_info") or {}
    cover = card.get("cover") or item.get("cover") or {}
    xsec_token = item.get("xsec_token") or card.get("xsec_token") or ""
    url = f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token:
        url += f"?xsec_token={xsec_token}"
    return {
        "note_id": str(note_id),
        "title": card.get("display_title") or item.get("display_title") or "",
        "author": user.get("nickname") or "",
        "author_id": user.get("user_id") or "",
        "url": url,
        "cover": cover.get("url") or "",
        "note_type": card.get("type") or "",
        "liked_count": str(interact.get("liked_count") or ""),
        "xsec_token": xsec_token,
        "extra": {"xsec_source": item.get("xsec_source") or ""},
    }


def _split_keywords(text: str) -> list[str]:
    return [k.strip() for k in (text or "").replace("，", ",").split(",") if k.strip()]


def _match_filters(title: str, includes: list[str], excludes: list[str]) -> bool:
    if any(word in title for word in excludes):
        return False
    if includes and not any(word in title for word in includes):
        return False
    return True


class XhsMonitorService:
    def __init__(
        self,
        repository: XhsMonitorRepository,
        xhs_service: Any,
        notifier: WebhookNotifier | None = None,
    ) -> None:
        self.repository = repository
        self.xhs_service = xhs_service
        self.notifier = notifier

    # ---- 拉取 ----

    async def _fetch(self, monitor: dict) -> tuple[bool, str, list[dict]]:
        if monitor["kind"] == "creator":
            ok, msg, notes = await self.xhs_service.user_notes(monitor["target"])
        else:
            ok, msg, notes = await self.xhs_service.search(
                SearchRequest(query=monitor["target"], require_num=SCAN_LIMIT)
            )
        if not ok:
            return False, msg or "拉取失败", []
        items = notes if isinstance(notes, list) else []
        normalized = [n for n in (normalize_note(i) for i in items) if n]
        return True, "", normalized

    # ---- 扫描一个目标 ----

    async def scan_monitor(self, monitor: dict) -> dict:
        monitor_id = monitor["id"]
        first_scan = not monitor.get("last_scan_at")
        try:
            ok, message, notes = await self._fetch(monitor)
        except Exception as exc:  # noqa: BLE001 - 扫描异常记入目标状态，不中断调度
            ok, message = False, f"{type(exc).__name__}: {exc}"

        if not ok:
            self.repository.update_monitor(
                monitor_id,
                {"last_scan_at": _now_iso(), "last_scan_status": "error", "last_error": message[:500]},
            )
            return {"ok": False, "message": message, "new_count": 0, "notified": False}

        includes = _split_keywords(monitor.get("include_keywords", ""))
        excludes = _split_keywords(monitor.get("exclude_keywords", ""))
        filtered = [n for n in notes if _match_filters(n["title"], includes, excludes)]

        fresh: list[dict] = []
        for note in filtered:
            if self.repository.note_exists(note["note_id"]):
                continue
            fresh.append(note)
            if first_scan and len(fresh) >= int(monitor.get("backfill_count", 10)):
                break

        new_ids: list[int] = []
        if fresh:
            # 首扫基线直接标记已通知；增量扫描插入后再统一推送
            for note in fresh:
                saved = self.repository.add_content(
                    {**note, "monitor_id": monitor_id, "notified": first_scan}
                )
                new_ids.append(saved["id"])

        notified = False
        if fresh and not first_scan and self.notifier is not None:
            titles = [n["title"] or n["note_id"] for n in fresh]
            preview = "、".join(titles[:5]) + (f" 等{len(titles)}篇" if len(titles) > 5 else "")
            monitor_label = monitor.get("name") or monitor["target"]
            try:
                await self.notifier.send(
                    "xhs_monitor",
                    f"心流 FlowPulse · 小红书监控新作品（{monitor_label}）",
                    f"发现 {len(fresh)} 篇新作品：{preview}",
                )
                self.repository.mark_notified(new_ids)
                notified = True
            except Exception:  # noqa: BLE001 - 推送失败不影响入库结果
                pass

        self.repository.update_monitor(
            monitor_id,
            {"last_scan_at": _now_iso(), "last_scan_status": "ok", "last_error": ""},
        )
        return {
            "ok": True,
            "message": f"扫描成功：{len(notes)} 条结果，{len(filtered)} 条通过过滤，{len(fresh)} 篇新作品",
            "new_count": len(fresh),
            "notified": notified,
        }

    # ---- 列表视图（含统计） ----

    def list_with_stats(self, status: str | None = None) -> list[dict]:
        stats = self.repository.content_stats()
        monitors = self.repository.list_monitors(status)
        for monitor in monitors:
            monitor["content_count"] = stats.get(monitor["id"], 0)
        return monitors
