import json

from douyin_transcribe.resolvers.share_page import (
    extract_douyin_url,
    extract_router_data,
    find_video_payload,
)


def test_extract_url_from_share_text():
    value = "Copy this https://v.douyin.com/example/ more text"
    assert extract_douyin_url(value) == "https://v.douyin.com/example/"


def test_extract_router_data_and_video():
    payload = {
        "loaderData": {
            "video": {
                "aweme_id": "123",
                "desc": "Example",
                "video": {"play_addr": {"url_list": ["https://media.example/video.mp4"]}},
            }
        }
    }
    html = f"<script>window._ROUTER_DATA = {json.dumps(payload)};</script>"
    assert find_video_payload(extract_router_data(html))["aweme_id"] == "123"
