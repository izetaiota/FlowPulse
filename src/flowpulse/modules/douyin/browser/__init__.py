"""抖音拦截式读取（T3.2）：patchright/playwright 打开页面，监听 XHR 响应拿数据。

- 用户作品：打开 /user/{sec_uid}，拦截 /aweme/v1/web/aweme/post 响应，滚动翻页；
- 关键词搜索：打开搜索页，拦截 /aweme/v1/web/search/item 响应，滚动翻页。

不做签名直连（D2 决策：纯浏览器先行，规避 a_bogus 失效风险）。
带账号 Cookie 时复用登录态（无 Cookie 也可尝试匿名读取，失败则报错提示先登录）。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote

from flowpulse.modules.browser import engine as browser_engine

USER_API_MARKER = "/aweme/v1/web/aweme/post"
SEARCH_API_MARKER = "/aweme/v1/web/search/item"

SCROLL_ROUNDS = 20
SCROLL_WAIT_SECONDS = 1.2


def normalize_aweme(item: dict) -> dict | None:
    """把拦截到的 aweme 对象规范化为监控作品记录字段。"""
    aweme_id = str(item.get("aweme_id") or "")
    if not aweme_id:
        return None
    author = (item.get("author") or {})
    desc = (item.get("desc") or "").strip()
    video = (item.get("video") or {})
    stats = (item.get("statistics") or {})
    cover = ""
    video_cover = (video.get("cover") or {}) or ((video.get("origin_cover") or {}))
    if isinstance(video_cover, dict):
        urls = video_cover.get("url_list") or []
        cover = urls[0] if urls else ""
    media_type = "video" if (item.get("video") or {}).get("play_addr") else "image"
    return {
        "aweme_id": aweme_id,
        "title": desc[:200],
        "author": author.get("nickname") or "",
        "author_id": author.get("sec_uid") or "",
        "url": f"https://www.douyin.com/video/{aweme_id}",
        "cover": cover,
        "media_type": media_type,
        "liked_count": str(stats.get("digg_count") or ""),
        "create_time": int(item.get("create_time") or 0),
        "extra": {
            "comment_count": stats.get("comment_count") or 0,
            "share_count": stats.get("share_count") or 0,
            "duration_ms": (video.get("duration") or 0) if isinstance(video, dict) else 0,
        },
    }


def sec_uid_from(target: str) -> str:
    """从主页 URL 或裸 sec_uid 提取 sec_uid。"""
    target = (target or "").strip()
    match = re.search(r"/user/([A-Za-z0-9_-]+)", target)
    if match:
        return match.group(1)
    return target


class DouyinBrowserFetcher:
    def __init__(self, get_login_state, profiles_root, headless: bool = True):
        """get_login_state: () -> (cookie_str | None, storage_state | None)（由装配层注入）。"""
        self._get_login_state = get_login_state
        self._profiles_root = profiles_root
        self._headless = headless

    async def _context(self):
        from flowpulse.modules.browser import ProfileAllocator

        cookie, storage_state = self._get_login_state()
        if storage_state is None and cookie:
            storage_state = browser_engine.storage_state_from_cookie(cookie)
        profile = ProfileAllocator(self._profiles_root).allocate("douyin", "fetch")
        return await browser_engine.launch_persistent_context(
            profile, headless=self._headless, storage_state=storage_state
        )

    async def _collect(
        self,
        url: str,
        api_marker: str,
        limit: int,
        extract_items,
    ) -> list[dict]:
        context = await self._context()
        collected: dict[str, dict] = {}
        try:
            page = context.pages[0] if context.pages else await context.new_page()

            async def handle_response(response) -> None:
                try:
                    if api_marker not in response.url:
                        return
                    payload = await response.json()
                    for raw in extract_items(payload):
                        normalized = normalize_aweme(raw)
                        if normalized:
                            collected[normalized["aweme_id"]] = normalized
                except Exception:  # noqa: BLE001 - 单个响应解析失败忽略
                    pass

            loop = asyncio.get_running_loop()
            page.on("response", lambda response: loop.create_task(handle_response(response)))
            await page.goto(url, wait_until="domcontentloaded")
            for _ in range(SCROLL_ROUNDS):
                if len(collected) >= limit:
                    break
                await page.mouse.wheel(0, 4000)
                await asyncio.sleep(SCROLL_WAIT_SECONDS)
            # 末尾再等一轮收尾响应
            await asyncio.sleep(1.0)
        finally:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
        return list(collected.values())[:limit]

    async def fetch_user_works(self, target: str, limit: int = 30) -> list[dict]:
        sec_uid = sec_uid_from(target)
        if not sec_uid:
            raise ValueError("无法从目标解析 sec_uid")
        url = f"https://www.douyin.com/user/{sec_uid}"

        def extract(payload: dict) -> list:
            return ((payload or {}).get("data") or {}).get("aweme_list") or []

        return await self._collect(url, USER_API_MARKER, limit, extract)

    async def fetch_search(self, keyword: str, limit: int = 30) -> list[dict]:
        url = f"https://www.douyin.com/search/{quote(keyword)}?type=video"

        def extract(payload: dict) -> list:
            data = (payload or {}).get("data") or {}
            return data.get("aweme_list") or [
                (item or {}).get("aweme_info") or item
                for item in (data.get("data") or [])  # 旧版结构 data.data[].aweme_info
            ]

        return await self._collect(url, SEARCH_API_MARKER, limit, extract)
