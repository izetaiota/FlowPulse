"""TikTok 原生签名直连 Fetcher（T5.3）：包装 TikTokNativeClient，接口对齐监控框架。

TikTok 走离线签名 HTTP 直连（offline_sign），无需浏览器；curl_cffi 为必需依赖
（未安装时优雅报错）。登录 Cookie 非必需——搜索接口匿名可用，带 Cookie 更稳。
"""

from __future__ import annotations

from flowpulse.modules.tiktok.client import TikTokNativeClient
from flowpulse.modules.tiktok.extract import normalize_tiktok_item

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class TiktokFetcher:
    def __init__(self, get_login_state, proxy: str = "", headless: bool = True):
        """get_login_state: () -> (cookie_str | None, storage_state | None)（Cookie 可空）。"""
        self._get_login_state = get_login_state
        self._proxy = proxy
        # headless 参数仅为对齐监控框架签名：原生直连无浏览器概念

    def _client(self) -> TikTokNativeClient:
        try:
            import curl_cffi  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("未安装 curl_cffi（pip install -e \".[xhs]\"），TikTok 直连不可用") from exc
        cookie, _ = self._get_login_state()
        return TikTokNativeClient(storage_state=cookie, user_agent=DEFAULT_UA, proxy=self._proxy)

    async def fetch_search(self, keyword: str, limit: int = 30) -> list[dict]:
        client = self._client()
        result = await client.search(keyword, count=max(1, min(50, limit)))
        if not result.compatible:
            raise RuntimeError(result.error or f"TikTok 接口失败：{result.category}")
        works = []
        for raw in result.items:
            normalized = normalize_tiktok_item(raw)
            if normalized:
                works.append(normalized)
        return works

    async def fetch_comments(self, aweme_id: str, author_unique_id: str = "", limit: int = 20) -> list[dict]:
        client = self._client()
        result = await client.comments(aweme_id, count=limit, author_unique_id=author_unique_id)
        if not result.compatible:
            raise RuntimeError(result.error or f"TikTok 评论接口失败：{result.category}")
        from flowpulse.modules.tiktok.extract import parse_tiktok_comment

        comments = []
        for raw in result.items:
            parsed = parse_tiktok_comment(raw)
            if parsed:
                comments.append(parsed)
        return comments
