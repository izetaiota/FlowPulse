import pytest

from douyin_transcribe.services.media import ensure_public_http_url


def test_rejects_private_media_url():
    with pytest.raises(RuntimeError):
        ensure_public_http_url("http://127.0.0.1/private.mp4")


def test_accepts_public_media_url():
    ensure_public_http_url("https://example.com/video.mp4")
