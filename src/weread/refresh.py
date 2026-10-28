"""微信读书 Cookie 自动续期：复用扫码登录留下的浏览器 profile，无头静默刷新。

每日（可配置）用 Playwright 无头打开 weread.qq.com，服务端会轮换 wr_skey，
提取最新 Cookie 写回并校验；profile 登录态也失效时标记凭证失效并告警，
提示用户重新扫码（重新扫码后 profile 恢复，续期继续生效）。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from weread.models import now_iso
from weread.notify import WebhookNotifier
from weread.qrlogin import WereadQrLoginManager
from weread.service import WereadService
from weread.storage import WereadRepository


class WereadCookieRefresher:
    def __init__(
        self,
        qr_login: WereadQrLoginManager,
        service: WereadService,
        repository: WereadRepository,
        notifier: WebhookNotifier | None = None,
        interval_hours: int = 24,
    ):
        self.qr_login = qr_login
        self.service = service
        self.repository = repository
        self.notifier = notifier
        self.interval_hours = max(0, int(interval_hours))
        self._task: asyncio.Task | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        state = self.repository.load_cookie_refresher_state()
        if self.interval_hours <= 0:
            state["enabled"] = False
            state["interval_hours"] = 0
            self.repository.save_cookie_refresher_state(state)
            return
        state["enabled"] = True
        state["interval_hours"] = self.interval_hours
        self.repository.save_cookie_refresher_state(state)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        # 从未跑过：先等一个完整周期；已超期（如服务重启导致计时重置）：立即补跑
        delay = self._seconds_until_due()
        if delay > 0:
            await asyncio.sleep(delay)
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - 后台循环不允许中断
                pass
            await asyncio.sleep(self.interval_hours * 3600)

    def _seconds_until_due(self) -> float:
        interval = self.interval_hours * 3600.0
        state = self.repository.load_cookie_refresher_state()
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
        # 上限封顶，防止时钟异常导致长时间休眠
        return max(0.0, min(remaining, interval))

    # ---- 状态 ----

    def status(self) -> dict:
        state = self.repository.load_cookie_refresher_state()
        state["task_alive"] = self._task is not None and not self._task.done()
        return state

    # ---- 单次执行 ----

    async def run_once(self) -> dict:
        state = self.repository.load_cookie_refresher_state()
        state["running"] = True
        state["last_run_at"] = now_iso()
        self.repository.save_cookie_refresher_state(state)
        result: dict = {}
        try:
            result = await self._refresh()
        finally:
            state = self.repository.load_cookie_refresher_state()
            state["running"] = False
            state["last_result"] = result
            self.repository.save_cookie_refresher_state(state)
        return result

    async def _refresh(self) -> dict:
        try:
            cookie = await self.qr_login.capture_cookie_headless()
        except Exception as exc:  # 浏览器/网络等一切异常都归为 browser_error，不外抛 500
            return {"ok": False, "reason": "browser_error", "message": str(exc)[:200]}

        if not cookie:
            credential = self.repository.get_credential()
            if not credential:
                # 用户主动删除过凭证（profile 已一并清除）：静默跳过，不告警不打扰
                return {"ok": False, "reason": "no_credential", "message": "未配置凭证，跳过续期"}
            # profile 登录态失效：标记凭证失效，提示重新扫码
            credential.valid = False
            credential.last_error = "浏览器登录态已过期，请到工作台重新扫码"
            credential.last_validated_at = now_iso()
            self.repository.update_credential(credential)
            if self.notifier:
                await self.notifier.send(
                    "weread_cookie_refresh",
                    "心流 FlowPulse · 微信读书 Cookie 需重新扫码",
                    "自动续期发现浏览器登录态已过期，请到「公众号订阅」页面点击「扫码登录」。",
                )
            return {"ok": False, "reason": "profile_expired", "message": "登录态已过期，请重新扫码"}

        previous = self.repository.get_credential()
        old_cookie = previous.cookie if previous else ""
        try:
            validation = await self.service.save_credential(cookie)
        except Exception as exc:  # 校验流程异常（网络等），Cookie 仍已保存
            return {"ok": False, "reason": "validate_error", "message": str(exc), "changed": cookie != old_cookie}
        ok = bool(validation.get("valid"))
        if not ok and self.notifier:
            await self.notifier.send(
                "weread_cookie_refresh",
                "心流 FlowPulse · 微信读书 Cookie 续期校验未通过",
                f"已提取新 Cookie 但校验未通过：{validation.get('message', '')}",
            )
        return {
            "ok": ok,
            "reason": "" if ok else "invalid_cookie",
            "message": validation.get("message", ""),
            "changed": cookie != old_cookie,
            "valid": ok,
        }
