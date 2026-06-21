from urllib.parse import urljoin

import httpx

from douyin_transcribe.models import VideoInfo
from douyin_transcribe.resolvers.base import ResolverError
from douyin_transcribe.resolvers.share_page import (
    extract_douyin_url,
    find_video_payload,
    first_url,
    get_path,
)


class ApiResolver:
    name = "resolver_api"

    def __init__(self, client: httpx.AsyncClient, base_url: str):
        self.client = client
        self.base_url = base_url.rstrip("/") + "/" if base_url else ""

    async def probe(self) -> bool:
        return bool(self.base_url)

    async def resolve(self, input_text: str) -> VideoInfo:
        source_url = extract_douyin_url(input_text)
        endpoint = urljoin(self.base_url, "api/hybrid/video_data")
        response = await self.client.get(endpoint, params={"url": source_url, "minimal": "false"})
        response.raise_for_status()
        payload = response.json()
        video = find_video_payload(payload)
        media_url = first_url(
            get_path(video, "video", "play_addr", "url_list")
            or get_path(video, "video", "play_addr_h264", "url_list")
        )
        if not media_url:
            raise ResolverError("Resolver API did not contain a playable media URL")
        return VideoInfo(
            aweme_id=str(video.get("aweme_id") or video.get("id") or "") or None,
            source_url=source_url,
            resolved_url=source_url,
            media_url=media_url,
            title=video.get("desc") or "Untitled Douyin video",
            author=get_path(video, "author", "nickname"),
            cover_url=first_url(get_path(video, "video", "cover", "url_list")),
            duration_ms=get_path(video, "video", "duration"),
            raw=video,
        )
