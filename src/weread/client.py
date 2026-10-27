"""微信读书 Web API 客户端。

接口细节（2026-10-27 实测，参考 we-mp-rss MIT）：
  - 书架:     GET /web/shelf/sync?userVid=&synckey=0&lectureSynckey=0
              （userVid 必须传空字符串，非空反而触发 -2012）
  - 文章列表: GET /web/mp/articles?bookId=<MP_WXS_xxx>&offset=0
              （部分账号已废弃恒返回 -2041，调用方需回退 cover）
  - 最新一篇: GET /api/mp/cover?bookId=<MP_WXS_xxx>
  - 业务码:   -2012 Cookie 失效 / -2010、-2041 需重新扫码 / 200013 频率限制
  - 链接坑:   微信读书把 token 里的 `_` 写成 `~`，必须还原，否则微信报「参数错误」
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from weread.models import MpArticle

WEREAD_BASE = "https://weread.qq.com"
MP_PREFIX = "MP_WXS_"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

AUTH_CODES = {-2010, -2012, -2014, -2041}
RATE_LIMIT_CODES = {200013}
CODE_GUIDE = {
    -2010: "需重新扫码登录",
    -2012: "Cookie 已失效，请重新粘贴",
    -2014: "账号配额耗尽",
    -2041: "登录态失效，需重新扫码",
    200013: "触发频率限制",
}


class WereadAPIError(Exception):
    """微信读书接口业务错误。kind: auth | rate_limit | api | network"""

    def __init__(self, kind: str, code: int | str, message: str):
        super().__init__(f"[{kind}] {code}: {message}")
        self.kind = kind
        self.code = code
        self.message = message


def build_mp_url(original_id: str) -> str:
    """由文章 originalId（短链 token）拼公众号原文链接，还原 `~`→`_`。"""
    token = str(original_id or "").strip().replace("~", "_")
    return f"https://mp.weixin.qq.com/s/{quote(token, safe='')}"


def link_from_review_id(review_id: str, book_id: str = "") -> str:
    """从 reviewId（MP_WXS_<bookId>_<token>）推导原文链接（cover 路径用）。"""
    token = str(review_id or "").strip()
    prefix = f"{book_id}_" if book_id else ""
    if prefix and token.startswith(prefix):
        token = token[len(prefix):]
    elif "_" in token:
        token = token.split("_", 1)[1]
    return build_mp_url(token)


def parse_articles_payload(payload: dict, book_id: str) -> list[MpArticle]:
    """解析 /web/mp/articles 的 groups → subReviews → review.mpInfo 结构。"""
    articles: list[MpArticle] = []
    for group in payload.get("reviews", []) or []:
        group_time = group.get("createTime", 0)
        for sub in group.get("subReviews", []) or []:
            review = sub.get("review") or {}
            mp_info = review.get("mpInfo") or {}
            review_id = review.get("reviewId") or sub.get("reviewId")
            if not review_id:
                continue
            articles.append(
                MpArticle(
                    review_id=str(review_id),
                    book_id=book_id,
                    title=mp_info.get("title", "") or review.get("content", ""),
                    link=build_mp_url(mp_info.get("originalId", "")),
                    cover=mp_info.get("pic_url", ""),
                    digest=(mp_info.get("content") or "")[:200],
                    publish_time=int(
                        mp_info.get("time") or review.get("createTime") or group_time or 0
                    ),
                )
            )
    return articles


def cover_to_article(payload: dict, book_id: str) -> MpArticle:
    """把 /api/mp/cover 的返回包装成单篇文章。"""
    review_id = payload.get("reviewId", "")
    return MpArticle(
        review_id=str(review_id),
        book_id=book_id,
        title=payload.get("title", ""),
        link=link_from_review_id(str(review_id), book_id),
        cover=payload.get("pic", ""),
        digest="",
        publish_time=0,
    )


class WereadClient:
    """带限速与错误映射的微信读书 Web API 客户端（异步）。"""

    def __init__(
        self,
        client: httpx.AsyncClient,
        cookie_provider: Callable[[], str],
        request_interval_seconds: float = 2.0,
    ):
        self._client = client
        self._cookie_provider = cookie_provider
        self._interval = max(0.0, request_interval_seconds)
        self._last_request_monotonic = 0.0
        self._lock = asyncio.Lock()

    # ---- 基础请求 ----

    def _headers(self) -> dict:
        cookie = self._cookie_provider() or ""
        return {
            "Cookie": cookie,
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": WEREAD_BASE,
            "Referer": f"{WEREAD_BASE}/",
        }

    async def _throttle(self) -> None:
        """微信读书有频率限制，请求之间保持最小间隔（加随机抖动）。"""
        async with self._lock:
            now = time.monotonic()
            wait = self._last_request_monotonic + self._interval - now
            if wait > 0:
                await asyncio.sleep(wait + random.uniform(0, min(1.0, self._interval / 2)))
            self._last_request_monotonic = time.monotonic()

    async def _get_json(self, path: str, params: dict) -> dict:
        await self._throttle()
        try:
            response = await self._client.get(
                f"{WEREAD_BASE}{path}", params=params, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise WereadAPIError("network", "network_error", str(exc)) from exc
        if response.status_code in (401, 499):
            raise WereadAPIError("auth", response.status_code, "登录态失效或配额耗尽")
        if response.status_code != 200:
            raise WereadAPIError("api", response.status_code, f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WereadAPIError("api", "invalid_json", f"{path} 返回非 JSON") from exc
        code = payload.get("errCode", payload.get("errcode", 0))
        try:
            code = int(code or 0)
        except (TypeError, ValueError):
            code = 0
        if code != 0:
            kind = "auth" if code in AUTH_CODES else "rate_limit" if code in RATE_LIMIT_CODES else "api"
            message = CODE_GUIDE.get(code) or str(payload.get("errMsg") or payload.get("errmsg") or code)
            raise WereadAPIError(kind, code, message)
        return payload

    # ---- 业务接口 ----

    async def fetch_shelf_books(self) -> list[dict]:
        """拉书架（用于凭证校验）。注意 userVid 必须传空字符串。"""
        payload = await self._get_json(
            "/web/shelf/sync", {"userVid": "", "synckey": 0, "lectureSynckey": 0}
        )
        return payload.get("books", []) or []

    async def fetch_articles(self, book_id: str, offset: int = 0) -> list[MpArticle]:
        """文章列表（部分账号已废弃此接口，会抛 auth 错误，调用方回退 cover）。"""
        payload = await self._get_json(
            "/web/mp/articles", {"bookId": book_id, "offset": offset}
        )
        return parse_articles_payload(payload, book_id)

    async def fetch_cover(self, book_id: str) -> tuple[MpArticle, dict]:
        """最新一篇文章 + 公众号元信息（name/avatar）。"""
        payload = await self._get_json("/api/mp/cover", {"bookId": book_id})
        if not payload.get("reviewId"):
            raise WereadAPIError("api", "empty_cover", "公众号未返回最新文章")
        meta = {"name": payload.get("name", ""), "avatar": payload.get("avatar", "")}
        return cover_to_article(payload, book_id), meta
