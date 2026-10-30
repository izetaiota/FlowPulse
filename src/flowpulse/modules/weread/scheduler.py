"""定时同步调度器：应用内置 asyncio 循环，状态持久化到 data/weread/。"""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from flowpulse.core.notify import WebhookNotifier
from flowpulse.modules.weread.client import WereadAPIError
from flowpulse.modules.weread.models import MpSubscription, now_iso
from flowpulse.modules.weread.service import WereadService
from flowpulse.modules.weread.storage import WereadRepository

# 检查粒度：每分钟看一次哪些订阅到期（支持订阅级更短的同步周期）
_TICK_SECONDS = 60.0
# 到期判断容差，避免 tick 边界抖动导致偶发跳过
_DUE_TOLERANCE_SECONDS = 5.0


class WereadScheduler:
    def __init__(
        self,
        service: WereadService,
        repository: WereadRepository,
        notifier: WebhookNotifier | None = None,
        interval_minutes: int = 120,
        qr_login: object | None = None,
    ):
        self.service = service
        self.repository = repository
        self.notifier = notifier
        self.interval_minutes = max(0, int(interval_minutes))
        # 扫码登录管理器（可选）：Cookie 失效告警时截图二维码推送到通知渠道
        self._qr_login = qr_login
        self._task: asyncio.Task | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        state = self.repository.load_scheduler_state()
        if self.interval_minutes <= 0:
            state["enabled"] = False
            state["interval_minutes"] = 0
            self.repository.save_scheduler_state(state)
            return
        state["enabled"] = True
        state["interval_minutes"] = self.interval_minutes
        self.repository.save_scheduler_state(state)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        # 从未跑过：先等一个完整周期（避免启动即请求微信读书）；已超期则立即补跑
        delay = self._seconds_until_due()
        if delay > 0:
            await asyncio.sleep(delay)
        while True:
            try:
                await self.run_tick()
            except Exception:  # noqa: BLE001 - 后台循环不允许中断
                pass
            await asyncio.sleep(_TICK_SECONDS)

    async def run_tick(self) -> dict:
        """按订阅粒度检查到期并同步：订阅级周期（sync_interval_minutes>0）优先，
        否则用全局 interval_minutes；到期的订阅逐个同步并聚合告警。"""
        if self.interval_minutes <= 0:
            return {"skipped": "disabled"}
        subs = self.service.list_subscriptions()
        due = [
            sub for sub in subs
            if self._sub_due(sub)
        ]
        if not due:
            return {"checked": len(subs), "synced": 0}
        self.repository.save_scheduler_state(
            {**self.repository.load_scheduler_state(), "running": True}
        )
        results = []
        try:
            for sub in due:
                results.append(await self.service.sync_subscription(sub.book_id))
        finally:
            state = self.repository.load_scheduler_state()
            state.update(
                running=False,
                last_run_at=now_iso(),
                last_result={
                    "ok_count": sum(1 for r in results if r.status == "ok"),
                    "error_count": sum(1 for r in results if r.status != "ok"),
                    "new_articles": sum(r.new_articles for r in results),
                },
            )
            self.repository.save_scheduler_state(state)
        await self._alert_results(results)
        return {"checked": len(subs), "synced": len(results), **state["last_result"]}

    def _sub_due(self, sub: MpSubscription) -> bool:
        interval = sub.sync_interval_minutes or self.interval_minutes
        if interval <= 0:
            return False
        if not sub.last_sync_at:
            return True
        try:
            last = datetime.fromisoformat(sub.last_sync_at)
        except (TypeError, ValueError):
            return True
        elapsed = (datetime.now(UTC) - last).total_seconds()
        return elapsed >= interval * 60 - _DUE_TOLERANCE_SECONDS

    async def _alert_results(self, results: list) -> None:
        """按同步结果聚合告警：登录失效优先（附二维码），其次普通失败。"""
        if not self.notifier or not results:
            return
        failures = [r for r in results if r.status != "ok"]
        auth_failures = [r for r in failures if r.status == "auth_error"]
        if auth_failures:
            names = "、".join(r.name or r.book_id for r in auth_failures)
            await self._send_auth_alert(
                f"以下订阅采集报登录失效：{names}\n"
                "自动续期未恢复，可扫通知附带的二维码（或到系统页面）重新授权。"
            )
        elif failures:
            names = "、".join(r.name or r.book_id for r in failures)
            await self.notifier.send(
                "weread_sync_error",
                "心流 FlowPulse · 公众号同步异常",
                f"以下订阅同步失败：{names}\n详情见工作台状态页。",
            )

    def _seconds_until_due(self) -> float:
        interval = self.interval_minutes * 60.0
        state = self.repository.load_scheduler_state()
        last = state.get("last_run_at")
        if not last:
            return interval
        try:
            last_dt = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            return interval
        remaining = (
            last_dt + timedelta(seconds=interval) - datetime.now(UTC)
        ).total_seconds()
        # 上限封顶，防止时钟异常导致长时间休眠
        return max(0.0, min(remaining, interval))

    # ---- 状态 ----

    def status(self) -> dict:
        state = self.repository.load_scheduler_state()
        state["task_alive"] = self._task is not None and not self._task.done()
        return state

    # ---- 单次执行 ----

    async def run_once(self) -> dict:
        state = self.repository.load_scheduler_state()
        state["running"] = True
        state["last_run_at"] = now_iso()
        self.repository.save_scheduler_state(state)
        result: dict = {}
        try:
            summary = await self.service.sync_all()
            result = {
                "ok_count": summary.ok_count,
                "error_count": summary.error_count,
                "new_articles": summary.new_articles,
                "finished_at": summary.finished_at,
            }
            await self._alert_results(summary.details)
        except WereadAPIError as exc:
            result = {"error": exc.message}
            if self.notifier and exc.kind == "auth":
                await self._send_auth_alert(
                    f"同步中断：{exc.message}\n"
                    "可扫通知附带的二维码（或到系统页面）重新授权。"
                )
        finally:
            state = self.repository.load_scheduler_state()
            state["running"] = False
            state["last_result"] = result
            self.repository.save_scheduler_state(state)
        return result

    async def _send_auth_alert(self, message: str) -> None:
        """Cookie 失效告警：有扫码登录管理器时附带二维码截图（飞书图消息），
        截图不可得（无浏览器/无桌面）退回纯文本，不阻塞同步主流程。"""
        if not self.notifier:
            return
        title = "心流 FlowPulse · 微信读书 Cookie 失效"
        image: str | None = None
        if self._qr_login is not None:
            try:
                status = self._qr_login.status()
                if status.get("state") not in {"pending", "validating"}:
                    await self._qr_login.start()  # 幂等：拉起扫码窗口供就近扫码
                await asyncio.sleep(8.0)  # 等浏览器打开登录页出现二维码
                image = await self._qr_login.qr_screenshot_base64()
            except Exception:
                image = None
        if image:
            await self.notifier.send_image("weread_auth", title, message, image)
        else:
            await self.notifier.send("weread_auth", title, message)
