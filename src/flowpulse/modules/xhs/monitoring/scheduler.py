"""小红书作品监控调度器：tick 轮询到期目标，逐个串行扫描（对齐 weread 调度器模式）。

到期判定基于 last_scan_at + interval_minutes（持久化，服务重启后过期目标立即补扫）；
串行 + 目标间隔 2 秒，避免连续打小红书接口触发风控。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from flowpulse.core.notify import WebhookNotifier
from flowpulse.modules.xhs.monitoring.service import XhsMonitorService
from flowpulse.modules.xhs.monitoring.store import XhsMonitorRepository

SCAN_GAP_SECONDS = 2.0


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class XhsMonitorScheduler:
    def __init__(
        self,
        service: XhsMonitorService,
        repository: XhsMonitorRepository,
        tick_seconds: int = 60,
        enabled: bool = True,
    ) -> None:
        self.service = service
        self.repository = repository
        self.tick_seconds = max(5, int(tick_seconds))
        self.enabled = enabled
        self._task: asyncio.Task | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
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
                await self.run_once()
            except Exception:  # noqa: BLE001 - 后台循环不允许中断
                pass
            await asyncio.sleep(self.tick_seconds)

    # ---- 单轮 ----

    def due_monitors(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        due: list[dict] = []
        for monitor in self.repository.list_monitors(status="active"):
            last = _parse_iso(monitor.get("last_scan_at"))
            if last is None or now >= last.astimezone(timezone.utc) + timedelta(
                minutes=int(monitor["interval_minutes"])
            ):
                due.append(monitor)
        return due

    async def run_once(self) -> dict:
        """扫描全部到期目标一次（console CLI / 立即触发共用）。"""
        due = self.due_monitors()
        results = {"scanned": 0, "new": 0, "errors": 0, "detail": []}
        for index, monitor in enumerate(due):
            if index:
                await asyncio.sleep(SCAN_GAP_SECONDS)
            result = await self.service.scan_monitor(monitor)
            results["scanned"] += 1
            results["new"] += result.get("new_count", 0)
            if not result.get("ok"):
                results["errors"] += 1
            results["detail"].append({"id": monitor["id"], "name": monitor.get("name"), **result})
        return results

    def status(self) -> dict:
        monitors = self.repository.list_monitors()
        active = [m for m in monitors if m["status"] == "active"]
        return {
            "enabled": self.enabled,
            "task_alive": self._task is not None and not self._task.done(),
            "tick_seconds": self.tick_seconds,
            "monitors": len(monitors),
            "active_monitors": len(active),
            "due_now": len(self.due_monitors()),
        }
