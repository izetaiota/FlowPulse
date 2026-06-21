from pathlib import Path

import pytest

from douyin_transcribe.models import Transcript, VideoInfo
from douyin_transcribe.resolvers.router import ResolverRouter
from douyin_transcribe.transcribers.router import TranscriberRouter


class FailingResolver:
    name = "failing"

    async def probe(self):
        return True

    async def resolve(self, input_text):
        raise RuntimeError("expected failure")


class WorkingResolver:
    name = "working"

    async def probe(self):
        return True

    async def resolve(self, input_text):
        return VideoInfo(
            source_url=input_text,
            resolved_url=input_text,
            media_url="https://example.com/video.mp4",
        )


class UnavailableTranscriber:
    name = "unavailable"

    async def probe(self):
        return False

    async def transcribe(self, audio_path):
        raise AssertionError("should not be called")


class WorkingTranscriber:
    name = "working"

    async def probe(self):
        return True

    async def transcribe(self, audio_path):
        return Transcript(engine=self.name, text="ok")


async def test_resolver_fallback():
    result = await ResolverRouter([FailingResolver(), WorkingResolver()]).resolve(
        "https://v.douyin.com/test/"
    )
    assert result.media_url == "https://example.com/video.mp4"


async def test_transcriber_auto_fallback(tmp_path: Path):
    result = await TranscriberRouter(
        [UnavailableTranscriber(), WorkingTranscriber()]
    ).transcribe(tmp_path / "audio.wav", "auto")
    assert result.text == "ok"


async def test_transcriber_auto_does_not_fall_back_to_mock(tmp_path: Path):
    mock = WorkingTranscriber()
    mock.name = "mock"

    with pytest.raises(RuntimeError, match="All transcribers failed"):
        await TranscriberRouter([mock]).transcribe(tmp_path / "audio.wav", "auto")


async def test_transcriber_allows_explicit_mock(tmp_path: Path):
    mock = WorkingTranscriber()
    mock.name = "mock"

    result = await TranscriberRouter([mock]).transcribe(tmp_path / "audio.wav", "mock")

    assert result.engine == "mock"
