"""快手拦截式读取（T5.1）：打开页面拦截 REST/GraphQL 响应（纯浏览器，无签名负担）。

- 用户作品：/profile/{uid}，拦截 /rest/v/profile/feed 与 /graphql（visionProfilePhotoList）；
- 关键词搜索：/search/video?searchKey=...，拦截 /rest/v/search/feed 与 GraphQL 搜索。
响应解析移植自 creatorhub（extract.py 多候选键兜底）。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import quote

from flowpulse.modules.browser import ProfileAllocator
from flowpulse.modules.browser import engine as browser_engine
from flowpulse.modules.ks.extract import _dig_feeds, _dig_rest_feeds, _search_feeds, normalize_ks_feed


def _profile_feeds(payload: dict) -> list:
    """用户作品：REST feed 优先，GraphQL visionProfilePhotoList 兜底。"""
    return _dig_rest_feeds(payload) or _dig_feeds(payload)

PROFILE_URL = "https://www.kuaishou.com/profile/{uid}"
SEARCH_URL = "https://www.kuaishou.com/search/video?searchKey={keyword}"
REST_PROFILE_MARKER = "/rest/v/profile/feed"
REST_SEARCH_MARKER = "/rest/v/search/feed"
GRAPHQL_MARKER = "/graphql"

SCROLL_ROUNDS = 20
SCROLL_WAIT_SECONDS = 1.5

KS_DOMAIN = ".kuaishou.com"


def ks_cookie_storage_state(cookie: str) -> dict | None:
    cookies = []
    for chunk in (cookie or "").split(";"):
        if "=" not in chunk:
            continue
        name, _, value = chunk.strip().partition("=")
        if name:
            cookies.append({"name": name, "value": value, "domain": KS_DOMAIN, "path": "/"})
    return {"cookies": cookies, "origins": []} if cookies else None


def has_ks_login_cookie(cookie: str) -> bool:
    return "passToken=" in (cookie or "") and "userId=" in (cookie or "")


def user_id_from(target: str) -> str:
    match = re.search(r"/profile/([A-Za-z0-9_-]+)", target or "")
    return match.group(1) if match else (target or "").strip()


class KsBrowserFetcher:
    def __init__(self, get_login_state, profiles_root: Path, headless: bool = True):
        self._get_login_state = get_login_state
        self._profiles_root = profiles_root
        self._headless = headless

    async def _context(self):
        cookie, storage_state = self._get_login_state()
        if storage_state is None and cookie:
            storage_state = ks_cookie_storage_state(cookie)
        profile = ProfileAllocator(self._profiles_root).allocate("ks", "fetch")
        return await browser_engine.launch_persistent_context(
            profile, headless=self._headless, storage_state=storage_state
        )

    async def _collect(self, url: str, limit: int, extract_feeds) -> list[dict]:
        context = await self._context()
        collected: dict[str, dict] = {}
        try:
            page = context.pages[0] if context.pages else await context.new_page()

            async def handle_response(response) -> None:
                try:
                    request_url = str(response.url or "")
                    if not any(m in request_url for m in (REST_PROFILE_MARKER, REST_SEARCH_MARKER, GRAPHQL_MARKER)):
                        return
                    payload = await response.json()
                    for raw in extract_feeds(payload):
                        normalized = normalize_ks_feed(raw)
                        if normalized:
                            collected[normalized["photo_id"]] = normalized
                except Exception:  # noqa: BLE001 - 单个响应解析失败忽略
                    pass

            loop = asyncio.get_running_loop()
            page.on("response", lambda response: loop.create_task(handle_response(response)))
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            for _ in range(SCROLL_ROUNDS):
                if len(collected) >= limit:
                    break
                await page.mouse.wheel(0, 4000)
                await asyncio.sleep(SCROLL_WAIT_SECONDS)
            await asyncio.sleep(1.0)
        finally:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
        return list(collected.values())[:limit]

    async def fetch_user_works(self, target: str, limit: int = 30) -> list[dict]:
        uid = user_id_from(target)
        if not uid:
            raise ValueError("无法从目标解析快手用户 ID")
        return await self._collect(PROFILE_URL.format(uid=uid), limit, _profile_feeds)

    async def fetch_search(self, keyword: str, limit: int = 30) -> list[dict]:
        return await self._collect(
            SEARCH_URL.format(keyword=quote(keyword)), limit, _search_feeds
        )
