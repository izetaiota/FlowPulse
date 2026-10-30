"""抖音作品监控服务与 API（T3.3）：fetcher 拉取 → 过滤 → 去重入库 → 新作品通知。

扫描语义与 xhs 监控一致（首扫基线不推送、增量去重、include/exclude 标题过滤）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from flowpulse.core.notify import WebhookNotifier
from flowpulse.modules.douyin.browser import DouyinBrowserFetcher
from flowpulse.modules.douyin.monitoring.store import DouyinMonitorRepository

SCAN_LIMIT = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _split_keywords(text: str) -> list[str]:
    return [k.strip() for k in (text or "").replace("，", ",").split(",") if k.strip()]


def _match_filters(title: str, includes: list[str], excludes: list[str]) -> bool:
    if any(word in title for word in excludes):
        return False
    if includes and not any(word in title for word in includes):
        return False
    return True


class DouyinMonitorService:
    def __init__(
        self,
        repository: DouyinMonitorRepository,
        fetcher: DouyinBrowserFetcher,
        notifier: WebhookNotifier | None = None,
    ) -> None:
        self.repository = repository
        self.fetcher = fetcher
        self.notifier = notifier

    async def _fetch(self, monitor: dict) -> tuple[bool, str, list[dict]]:
        if monitor["kind"] == "creator":
            works = await self.fetcher.fetch_user_works(monitor["target"], limit=SCAN_LIMIT)
        else:
            works = await self.fetcher.fetch_search(monitor["target"], limit=SCAN_LIMIT)
        return True, "", works

    async def scan_monitor(self, monitor: dict) -> dict:
        monitor_id = monitor["id"]
        first_scan = not monitor.get("last_scan_at")
        try:
            ok, message, works = await self._fetch(monitor)
        except Exception as exc:  # noqa: BLE001 - 扫描异常记入目标状态，不中断调度
            ok, message = False, f"{type(exc).__name__}: {exc}"

        if not ok:
            self.repository.update_monitor(
                monitor_id,
                {
                    "last_scan_at": _now_iso(),
                    "last_scan_status": "error",
                    "last_error": message[:500],
                },
            )
            return {"ok": False, "message": message, "new_count": 0, "notified": False}

        includes = _split_keywords(monitor.get("include_keywords", ""))
        excludes = _split_keywords(monitor.get("exclude_keywords", ""))
        filtered = [w for w in works if _match_filters(w["title"], includes, excludes)]

        fresh: list[dict] = []
        for work in filtered:
            if self.repository.aweme_exists(work["aweme_id"]):
                continue
            fresh.append(work)
            if first_scan and len(fresh) >= int(monitor.get("backfill_count", 10)):
                break

        new_ids: list[int] = []
        if fresh:
            for work in fresh:
                saved = self.repository.add_content(
                    {**work, "monitor_id": monitor_id, "notified": first_scan}
                )
                new_ids.append(saved["id"])

        notified = False
        if fresh and not first_scan and self.notifier is not None:
            titles = [w["title"] or w["aweme_id"] for w in fresh]
            preview = "、".join(titles[:5]) + (f" 等{len(titles)}条" if len(titles) > 5 else "")
            monitor_label = monitor.get("name") or monitor["target"]
            try:
                await self.notifier.send(
                    "douyin_monitor",
                    f"心流 FlowPulse · 抖音监控新作品（{monitor_label}）",
                    f"发现 {len(fresh)} 条新作品：{preview}",
                )
                self.repository.mark_notified(new_ids)
                notified = True
            except Exception:  # noqa: BLE001 - 推送失败不影响入库
                pass

        self.repository.update_monitor(
            monitor_id, {"last_scan_at": _now_iso(), "last_scan_status": "ok", "last_error": ""}
        )
        return {
            "ok": True,
            "message": (
                f"扫描成功：{len(works)} 条结果，{len(filtered)} 条通过过滤，{len(fresh)} 条新作品"
            ),
            "new_count": len(fresh),
            "notified": notified,
        }

    def list_with_stats(self, status: str | None = None) -> list[dict]:
        stats = self.repository.content_stats()
        monitors = self.repository.list_monitors(status)
        for monitor in monitors:
            monitor["content_count"] = stats.get(monitor["id"], 0)
        return monitors
