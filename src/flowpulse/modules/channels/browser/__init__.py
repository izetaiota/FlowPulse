"""视频号拦截式读取（T5.2）：打开创作者助手页，拦截 mmfinderassistant-bin 响应。

- 资料：/platform 首页，拦截 auth/get_auth_info；
- 作品：/platform/post/list（视频）与 finderNewLifePostList（图文），拦截 post/post_list 与
  statistic/post_list（统计响应也带作品列表），滚动翻页。
加密 CDN 媒体只记元数据（见 extract.parse_post）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from flowpulse.modules.browser import ProfileAllocator
from flowpulse.modules.browser import engine as browser_engine
from flowpulse.modules.channels.extract import dig_posts, parse_post, parse_profile

BASE = "https://channels.weixin.qq.com"
PLATFORM_URL = BASE + "/platform"
POST_VIDEO_LIST_URL = BASE + "/platform/post/list"
POST_IMAGE_LIST_URL = BASE + "/platform/post/finderNewLifePostList"

AUTH_API = "mmfinderassistant-bin/auth/"
POST_LIST_API = "mmfinderassistant-bin/post/post_list"
STAT_API = "mmfinderassistant-bin/statistic/post_list"

SCROLL_ROUNDS = 10
SCROLL_WAIT_SECONDS = 1.8
DOMAIN = ".weixin.qq.com"


def channels_storage_from_cookies(cookies: list[dict]) -> dict | None:
    scoped = [c for c in cookies if "weixin.qq.com" in (c.get("domain") or "")]
    return {"cookies": scoped, "origins": []} if scoped else None


class ChannelsBrowserFetcher:
    def __init__(self, get_login_state, profiles_root: Path, headless: bool = True):
        self._get_login_state = get_login_state
        self._profiles_root = profiles_root
        self._headless = headless

    async def _open(self, url: str):
        _, storage_state = self._get_login_state()
        profile = ProfileAllocator(self._profiles_root).allocate("channels", "fetch")
        context = await browser_engine.launch_persistent_context(
            profile, headless=self._headless, storage_state=storage_state
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        return context, page

    @staticmethod
    def _logged_out(page) -> bool:
        return "/login" in (page.url or "")

    async def fetch_profile(self) -> dict:
        """打开助手首页拿资料；返回 {ok, profile?, error?, logged_out}。"""
        profile: dict = {}
        context, page = await self._open(PLATFORM_URL)

        async def on_response(response) -> None:
            nonlocal profile
            try:
                if AUTH_API not in str(response.url or ""):
                    return
                parsed = parse_profile(await response.json())
                if parsed:
                    profile = parsed
            except Exception:  # noqa: BLE001
                pass

        loop = asyncio.get_running_loop()
        page.on("response", lambda r: loop.create_task(on_response(r)))
        try:
            await page.wait_for_timeout(3500)
            if self._logged_out(page):
                return {"ok": False, "logged_out": True, "error": "视频号助手未登录"}
            if not profile:
                return {"ok": False, "logged_out": False, "error": "未拦截到资料接口（页面可能改版）"}
            return {"ok": True, "profile": profile}
        finally:
            await context.close()

    async def fetch_works(self, limit: int = 100) -> dict:
        """依次打开视频/图文管理页，拦截作品列表；返回 {ok, works, error?, logged_out}。"""
        collected: dict[str, dict] = {}
        context = None
        try:
            for list_url in (POST_VIDEO_LIST_URL, POST_IMAGE_LIST_URL):
                context, page = await self._open(list_url)

                async def on_response(response) -> None:
                    try:
                        url = str(response.url or "")
                        if POST_LIST_API not in url and STAT_API not in url:
                            return
                        for raw in dig_posts(await response.json()):
                            parsed = parse_post(raw)
                            if parsed:
                                collected[parsed["object_id"]] = parsed
                    except Exception:  # noqa: BLE001
                        pass

                loop = asyncio.get_running_loop()
                page.on("response", lambda r: loop.create_task(on_response(r)))
                if self._logged_out(page):
                    return {"ok": False, "logged_out": True, "error": "视频号助手未登录"}
                for _ in range(SCROLL_ROUNDS):
                    if len(collected) >= limit:
                        break
                    await page.mouse.wheel(0, 4000)
                    await asyncio.sleep(SCROLL_WAIT_SECONDS)
                await context.close()
                context = None
            return {"ok": True, "works": list(collected.values())[:limit]}
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:  # noqa: BLE001
                    pass
