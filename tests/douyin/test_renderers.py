from douyin.models import Transcript, TranscriptSegment, VideoInfo
from douyin.renderers.artifacts import render_markdown, render_srt


def test_srt_rendering():
    transcript = Transcript(
        engine="mock",
        text="Hello",
        segments=[TranscriptSegment(start_ms=0, end_ms=1250, text="Hello")],
    )
    assert "00:00:00,000 --> 00:00:01,250" in render_srt(transcript)


def test_markdown_rendering():
    video = VideoInfo(
        source_url="https://v.douyin.com/a/",
        resolved_url="https://www.douyin.com/video/1",
        media_url="https://media.example/video.mp4",
        title="Example",
    )
    transcript = Transcript(engine="mock", text="Hello")
    result = render_markdown(video, transcript)
    assert "# Example" in result
    assert "Hello" in result


def test_srt_falls_back_to_full_transcript():
    result = render_srt(Transcript(engine="sensevoice", text="Full transcript"))
    assert "Full transcript" in result
