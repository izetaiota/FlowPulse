import json
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from flowpulse.modules.douyin.models import VideoInfo
from flowpulse.modules.douyin.resolvers.base import ResolverError

URL_RE = re.compile(r"https?://(?:[\w-]+\.)?(?:douyin\.com|iesdouyin\.com)/[^\s]+", re.IGNORECASE)
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
)


class SharePageResolver:
    name = "share_page"

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def probe(self) -> bool:
        return True

    async def resolve(self, input_text: str) -> VideoInfo:
        source_url = extract_douyin_url(input_text)
        response = await self.client.get(source_url, headers={"User-Agent": IPHONE_UA})
        response.raise_for_status()
        data = extract_router_data(response.text)
        video = find_video_payload(data)
        media_url = first_url(
            get_path(video, "video", "play_addr", "url_list")
            or get_path(video, "video", "play_addr_h264", "url_list")
        )
        if not media_url:
            raise ResolverError("Share page did not contain a playable media URL")
        return VideoInfo(
            aweme_id=str(video.get("aweme_id") or video.get("id") or "") or None,
            source_url=source_url,
            resolved_url=str(response.url),
            media_url=media_url.replace("playwm", "play"),
            title=video.get("desc") or "Untitled Douyin video",
            author=get_path(video, "author", "nickname"),
            cover_url=first_url(get_path(video, "video", "cover", "url_list")),
            duration_ms=get_path(video, "video", "duration"),
            raw=video,
        )


def extract_douyin_url(value: str) -> str:
    match = URL_RE.search(value)
    if not match:
        raise ResolverError("Input does not contain a supported Douyin URL")
    return match.group(0).rstrip("),.;")


def extract_router_data(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="RENDER_DATA")
    if script and script.string:
        from urllib.parse import unquote

        return json.loads(unquote(script.string))

    patterns = [
        r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>",
        r"window\._ROUTER_DATA\s*=\s*(\{.*\})\s*;",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    raise ResolverError("Share page did not contain ROUTER_DATA")


def find_video_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if isinstance(value.get("video"), dict) and (
            "aweme_id" in value or "desc" in value or "author" in value
        ):
            return value
        for item in value.values():
            found = find_video_payload(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_video_payload(item)
            if found:
                return found
    return {}


def get_path(value: Any, *parts: str) -> Any:
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def first_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith("http"):
        return value
    if isinstance(value, list):
        return next(
            (item for item in value if isinstance(item, str) and item.startswith("http")),
            None,
        )
    return None
