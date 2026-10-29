"""小红书凭证定时校验：登录态掉线时推送 Webhook 告警（对齐 weread 调度器模式）。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from flowpulse.core.notify import WebhookNotifier
from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.modules.xhs.integration.service import XhsService

PLATFORMS = ("pc", "creator")

DEFAULT_STATE: dict = {
    "enabled": False,
    "interval_minutes": 0,
    "running": False,
    "last_run_at": None,
    "last_result": None,
}


class XhsCredentialChecker:
    def __init__(
        self,
        service: XhsService,
        data_dir,
        notifier: WebhookNotifier | None = None,
        interval_minutes: int = 360,
    ):
        self.service = service
        self.notifier = notifier
        self.interval_minutes = max(0, int(interval_minutes))
        self._state_path = data_dir / "xhs" / "credential_check.json"
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._task: asyncio.Task | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        state = self.status(populate=False)
        if self.interval_minutes <= 0:
            state["enabled"] = False
            state["interval_minutes"] = 0
            self._write(state)
            return
        state["enabled"] = True
        state["interval_minutes"] = self.interval_minutes
        self._write(state)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        # 未跑过等满一个周期；已超期（服务重启等）立即补跑
        delay = self._seconds_until_due()
        if delay > 0:
            await asyncio.sleep(delay)
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - 后台循环不允许中断
                pass
            await asyncio.sleep(self.interval_minutes * 60)

    def _seconds_until_due(self) -> float:
        interval = self.interval_minutes * 60.0
        state = self._read()
        last = state.get("last_run_at")
        if not last:
            return interval
        try:
            last_dt = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            return interval
        remaining = (
            last_dt + timedelta(seconds=interval) - datetime.now(timezone.utc)
        ).total_seconds()
        return max(0.0, min(remaining, interval))

    # ---- 状态 ----

    def _read(self) -> dict:
        return read_json(self._state_path, dict(DEFAULT_STATE))

    def _write(self, state: dict) -> None:
        atomic_write_json(self._state_path, state)

    def status(self, populate: bool = True) -> dict:
        state = self._read()
        if populate:
            state["task_alive"] = self._task is not None and not self._task.done()
        return state

    # ---- 单次执行 ----

    async def run_once(self) -> dict:
        state = self._read()
        state["running"] = True
        self._write(state)
        previous = state.get("last_result") or {}
        results: dict[str, dict] = {}
        try:
            for platform in PLATFORMS:
                try:
                    status = await self.service.login_status(platform)
                    results[platform] = {
                        "logged_in": status.logged_in,
                        "user_id": status.user_id,
                        "message": status.message,
                    }
                    fell_off = (previous.get(platform) or {}).get("logged_in") is True and not status.logged_in
                    if fell_off and self.notifier:
                        await self.notifier.send(
                            "xhs_credential",
                            "心流 FlowPulse · 小红书登录态失效",
                            f"平台 {platform} 的登录态已掉线，请到「小红书工作台」重新扫码或更新 Cookie。",
                        )
                except Exception as exc:  # noqa: BLE001 - 单平台失败不影响其他
                    results[platform] = {"logged_in": None, "message": str(exc)[:120]}
        finally:
            state = self._read()
            state["running"] = False
            state["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            state["last_result"] = results
            self._write(state)
        return results
