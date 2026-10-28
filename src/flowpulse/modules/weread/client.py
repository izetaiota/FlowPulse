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
import re
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from flowpulse.modules.weread.models import MpArticle

WEREAD_BASE = "https://weread.qq.com"
MP_PREFIX = "MP_WXS_"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

AUTH_CODES = {-2010, -2012, -2014, -2041}
RATE_LIMIT_CODES = {200013}
# 触发频率限制（200013）后的全局冷却时间：冷却期内直接拒绝请求，不再打接口
RATE_LIMIT_COOLDOWN_SECONDS = 600.0
# 公开文章页大小上限（实测约 3.5MB，留足余量），流式读取防异常超大页撑爆内存
PUBLIC_PAGE_MAX_BYTES = 20 * 1024 * 1024
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


# ---- 正文提取（移植自 we-mp-rss MIT 实现，实测 2026-10 微信改版后走 content_noencode 兜底）----


def _extract_js_single_quoted(html: str, marker: str) -> str:
    """从页面 JS 里按转义感知方式提取单引号字符串。"""
    index = html.find(marker)
    if index < 0:
        return ""
    index += len(marker)
    out: list[str] = []
    k = index
    while k < len(html):
        ch = html[k]
        if ch == "\\":
            out.append(html[k : k + 2])
            k += 2
            continue
        if ch == "'":
            break
        out.append(ch)
        k += 1
    return "".join(out)


def _js_unescape(s: str) -> str:
    out: list[str] = []
    m = 0
    while m < len(s):
        c = s[m]
        if c == "\\" and m + 1 < len(s):
            nxt = s[m + 1]
            if nxt == "x" and m + 3 < len(s):
                try:
                    out.append(chr(int(s[m + 2 : m + 4], 16)))
                    m += 4
                    continue
                except ValueError:
                    pass
            mapping = {"n": "\n", "t": "\t", "r": "\r", "'": "'", '"': '"', "\\": "\\"}
            out.append(mapping.get(nxt, nxt))
            m += 2
        else:
            out.append(c)
            m += 1
    return "".join(out)


def _extract_content_noencode(html: str) -> str:
    """兜底：从页面 JS 变量 content_noencode 提取全文纯文本（换行为 \\x0a），按段落转 <p>。"""
    raw = _extract_js_single_quoted(html, "content_noencode: '")
    if not raw:
        raw = _extract_js_single_quoted(html, "content_noencode:'")
    if not raw:
        return ""
    text = _js_unescape(raw).strip()
    if not text:
        return ""
    paragraphs = []
    for part in text.split("\n"):
        part = part.strip()
        if not part:
            continue
        part = part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        paragraphs.append(f"<p>{part}</p>")
    return "".join(paragraphs)


def extract_mp_content(html: str) -> str:
    """从文章页提取正文 HTML。

    优先 #js_content / .rich_media_content 节点（老版页面，含富文本）；
    新版页面两者均无，全文在 JS 变量 content_noencode（纯文本，图片会丢失）。
    """
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
    if content is None:
        fallback = _extract_content_noencode(html or "")
        if fallback:
            return fallback
        raise WereadAPIError("api", "invalid_content", "未在页面中找到文章正文")
    for element in content.select("script, style"):
        element.decompose()
    # 微信图片懒加载：真实 URL 在 data-src，静态抓取需回填到 src
    for img in content.select("img[data-src]"):
        img["src"] = img["data-src"]
    return content.decode_contents().strip()


def harden_images(html: str) -> str:
    """给 img 加 referrerpolicy=no-referrer，绕过微信图片防盗链（站内直显）。"""
    return re.sub(r"<img(?![^>]*referrerpolicy)", '<img referrerpolicy="no-referrer"', html)


# 公开文章页里的发布时间戳标记（实测 2026-10 页面三种都存在，值一致）
_PUBLISH_TIME_PATTERNS = (
    re.compile(r"var\s+ct\s*=\s*[\"'](\d{9,11})[\"']"),
    re.compile(r"oriCreateTime\s*=\s*[\"'](\d{9,11})[\"']"),
    re.compile(r"[\"']create_time[\"']\s*[:=]\s*[\"']?(\d{9,11})"),
)


def extract_publish_time(html: str) -> int:
    """从公开文章页提取发布时间戳（秒）；识别不了返回 0。"""
    for pattern in _PUBLISH_TIME_PATTERNS:
        match = pattern.search(html or "")
        if match:
            return int(match.group(1))
    return 0


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
        self._rate_limited_until = 0.0
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
        """微信读书有频率限制，请求之间保持最小间隔（加随机抖动）。

        触发过 200013 后进入冷却期：期间不再发请求，直接抛错让上层记录/告警。
        """
        async with self._lock:
            now = time.monotonic()
            cooldown_remaining = self._rate_limited_until - now
            if cooldown_remaining > 0:
                raise WereadAPIError(
                    "rate_limit",
                    "cooldown",
                    f"频率限制冷却中，约 {int(cooldown_remaining)} 秒后自动恢复",
                )
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
            if kind == "rate_limit":
                self._rate_limited_until = time.monotonic() + RATE_LIMIT_COOLDOWN_SECONDS
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

    async def fetch_content_html(self, review_id: str) -> str:
        """兜底路径：微信读书代理页正文（依赖 Cookie，比 cover 接口更严格）。"""
        await self._throttle()
        try:
            response = await self._client.get(
                f"{WEREAD_BASE}/web/mp/content",
                params={"reviewId": review_id},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise WereadAPIError("network", "network_error", str(exc)) from exc
        if response.status_code in (401, 499):
            raise WereadAPIError("auth", response.status_code, "登录态失效或配额耗尽")
        if response.status_code != 200:
            raise WereadAPIError("api", response.status_code, f"HTTP {response.status_code}")
        text = response.text
        # 该接口业务错误以 HTTP 200 + JSON 返回（如 -2012 登录超时），先嗅探再当 HTML 解析
        if text.lstrip().startswith("{"):
            try:
                payload = response.json()
                code = payload.get("errCode", payload.get("errcode", 0))
                if code:
                    kind = "auth" if int(code) in AUTH_CODES else "api"
                    raise WereadAPIError(kind, int(code), str(payload.get("errMsg") or code))
            except ValueError:
                pass
        content = extract_mp_content(text)
        return harden_images(content)

    async def fetch_public_article(self, link: str) -> tuple[str, int]:
        """主路径：直接抓 mp.weixin.qq.com 公开原文页（无需 Cookie，含完整富文本）。

        返回 (正文 HTML, 发布时间戳)。cover 通道拿不到发布时间，靠这里补。
        流式读取并限制大小，异常超大页面直接放弃。
        """
        await self._throttle()
        try:
            async with self._client.stream(
                "GET",
                link,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            ) as response:
                if response.status_code != 200:
                    raise WereadAPIError("api", response.status_code, f"HTTP {response.status_code}")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > PUBLIC_PAGE_MAX_BYTES:
                    raise WereadAPIError(
                        "api", "too_large", f"文章页过大（{int(declared) // 1048576}MB），已跳过"
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > PUBLIC_PAGE_MAX_BYTES:
                        raise WereadAPIError("api", "too_large", "文章页超过大小上限，已跳过")
                    chunks.append(chunk)
                html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        except httpx.HTTPError as exc:
            raise WereadAPIError("network", "network_error", str(exc)) from exc
        content = extract_mp_content(html)
        return harden_images(content), extract_publish_time(html)
