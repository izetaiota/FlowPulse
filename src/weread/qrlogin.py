"""微信读书扫码登录（Playwright 驱动本机 Chrome，思路参考 we-mp-rss MIT）。

流程：弹一个可见浏览器窗口打开 weread.qq.com 登录页 → 用户手机微信扫码 →
轮询浏览器 Cookie 直到出现 wr_vid/wr_skey → 回调 on_cookie 校验并入库。

浏览器使用持久化 profile（data/weread/browser_profile），登录态留在本机，
后续 Cookie 自动续期（阶段 5）可复用、无需重复扫码。
微信读书没有公开的纯 HTTP 扫码接口，二维码只能来自真实页面，因此此模块
依赖 playwright；未安装时给出明确提示而不是崩溃。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from weread.models import now_iso

# 登录成功后窗口停留几秒再关，让用户看到"登录成功"的页面反馈
_CLOSE_DELAY_SECONDS = 2.5
_POLL_INTERVAL_SECONDS = 2.0
_LOGIN_URL = "https://weread.qq.com/#login"
_COOKIE_URL = "https://weread.qq.com"

# 尝试顺序：本机 Chrome → 本机 Edge → playwright 自带 Chromium
_BROWSER_CHANNELS: list[dict | None] = [{"channel": "chrome"}, {"channel": "msedge"}, None]


def _has_login_cookie(cookie_pairs: list[dict]) -> bool:
    names = {pair["name"] for pair in cookie_pairs}
    return "wr_vid" in names and "wr_skey" in names


def _cookie_string(cookie_pairs: list[dict]) -> str:
    return "; ".join(f"{pair['name']}={pair['value']}" for pair in cookie_pairs if pair.get("value"))


class WereadQrLoginManager:
    """单例式扫码会话：start 幂等，同一时刻只允许一个浏览器登录窗口。"""

    def __init__(
        self,
        profile_dir: Path,
        on_cookie: Callable[[str], Awaitable[dict]],
        scan_timeout_seconds: float = 300.0,
    ):
        self._profile_dir = profile_dir
        self._on_cookie = on_cookie
        self._scan_timeout = scan_timeout_seconds
        self._state = "idle"
        self._message = ""
        self._page_url = ""
        self._started_at: str | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        # 同一持久化 profile 同时只能开一个浏览器实例（扫码窗口与无头续期互斥）
        self._browser_lock = asyncio.Lock()

    # ---- 对外接口 ----

    def status(self) -> dict:
        return {
            "state": self._state,
            "message": self._message,
            "page_url": self._page_url,
            "started_at": self._started_at,
        }

    async def start(self) -> dict:
        async with self._lock:
            if self._task and not self._task.done():
                return self.status()
            self._state = "pending"
            self._message = "正在打开浏览器，请在弹出窗口中用微信扫码登录"
            self._started_at = now_iso()
            self._task = asyncio.create_task(self._run())
        return self.status()

    async def cancel(self) -> dict:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._state in {"pending", "validating"}:
            self._state = "cancelled"
            self._message = "已取消扫码登录"
        return self.status()

    async def aclose(self) -> None:
        """应用关停时调用，避免遗留浏览器进程。"""
        await self.cancel()

    async def capture_cookie_headless(self) -> str:
        """无头续期：用持久化 profile 静默打开微信读书，提取当前登录 Cookie。

        返回空串表示 profile 登录态已失效（需要重新扫码）。
        与扫码窗口共用同一 profile，二者通过 _browser_lock 互斥。
        """
        if self._task and not self._task.done():
            raise RuntimeError("扫码登录窗口进行中，请等扫码结束再续期")
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("服务器未安装 playwright，无法续期（pip install playwright）") from exc

        async with self._browser_lock:
            async with async_playwright() as playwright:
                context, _channel = await self._launch(playwright, headless=True)
                try:
                    page = context.pages[0] if context.pages else await context.new_page()
                    await page.goto(_COOKIE_URL, wait_until="domcontentloaded", timeout=45_000)
                    # 打开页面会触发服务端轮换 wr_skey（Set-Cookie），稍等其落盘
                    await asyncio.sleep(2.0)
                    cookie_pairs = await context.cookies(_COOKIE_URL)
                    return _cookie_string(cookie_pairs) if _has_login_cookie(cookie_pairs) else ""
                finally:
                    await context.close()

    # ---- 内部流程 ----

    def _fail(self, message: str) -> None:
        self._state = "failed"
        self._message = message

    async def _run(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self._fail("服务器未安装 playwright，无法扫码（pip install playwright）")
            return

        try:
            async with async_playwright() as playwright:
                async with self._browser_lock:
                    await self._run_in_browser(playwright)
        except asyncio.CancelledError:
            self._state = "cancelled"
            self._message = "已取消扫码登录"
            raise
        except Exception as exc:
            text = str(exc)
            if "Target closed" in text or "Target page, context or browser has been closed" in text:
                self._fail("浏览器窗口被关闭，扫码中断。请重新点击「扫码登录」")
            else:
                self._fail(f"扫码登录失败：{text[:200]}")

    async def _run_in_browser(self, playwright) -> None:
        """在已持有的浏览器锁内完成一次扫码会话（含开关浏览器）。"""
        context = None
        try:
            context, _channel = await self._launch(playwright)
            page = context.pages[0] if context.pages else await context.new_page()
            self._page_url = _LOGIN_URL
            await page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(1.5)

            cookie_pairs = await context.cookies(_COOKIE_URL)
            if not _has_login_cookie(cookie_pairs):
                # 登录页一般自动弹二维码；兜底尝试点一下"登录"入口
                await self._try_click_login(page)
                cookie_pairs = await self._scan_loop(context)

            self._state = "validating"
            self._message = "已捕获登录态，正在校验 Cookie"
            cookie = _cookie_string(cookie_pairs)
            try:
                result = await self._on_cookie(cookie)
            except Exception as exc:  # 校验流程自身异常（网络等）
                self._fail(f"Cookie 已捕获但校验异常：{exc}")
                return
            if result.get("valid"):
                self._state = "success"
                self._message = f"扫码登录成功，Cookie 已保存并校验通过（{result.get('message', '')}）"
            else:
                self._state = "failed"
                self._message = f"扫码拿到了 Cookie，但校验未通过：{result.get('message', '')}"
            await asyncio.sleep(_CLOSE_DELAY_SECONDS)
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

    async def _launch(self, playwright, headless: bool = False):
        errors = []
        for kwargs in _BROWSER_CHANNELS:
            try:
                context = await playwright.chromium.launch_persistent_context(
                    str(self._profile_dir),
                    headless=headless,
                    viewport=None,  # 使用真实窗口尺寸
                    **(kwargs or {}),
                )
                return context, (kwargs or {}).get("channel")
            except Exception as exc:  # 本机没有该浏览器就换下一个
                errors.append(f"{kwargs or 'chromium'}: {str(exc)[:80]}")
        raise RuntimeError("无法启动浏览器（" + " | ".join(errors) + "）")

    async def _try_click_login(self, page) -> None:
        """二维码没自动弹出时，尽力点一下登录入口；点不到也不阻塞（用户可手动点）。"""
        for selector in [
            page.get_by_text("登录", exact=True),
            page.locator("nav", has_text="登录").first,
        ]:
            try:
                await selector.first.click(timeout=2_000)
                return
            except Exception:
                continue

    async def _scan_loop(self, context) -> list[dict]:
        """轮询浏览器 Cookie 直到登录成功；超时抛错。"""
        deadline = datetime.now(timezone.utc).timestamp() + self._scan_timeout
        self._message = "浏览器窗口已打开，请用微信扫码授权（二维码见弹出窗口）"
        while datetime.now(timezone.utc).timestamp() < deadline:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            try:
                cookie_pairs = await context.cookies(_COOKIE_URL)
                self._page_url = context.pages[0].url if context.pages else ""
            except Exception as exc:
                raise RuntimeError(f"浏览器窗口被关闭，扫码中断（{str(exc)[:80]}）") from exc
            if _has_login_cookie(cookie_pairs):
                return cookie_pairs
        raise RuntimeError("等待扫码超时（5 分钟），请重新点击「扫码登录」")
