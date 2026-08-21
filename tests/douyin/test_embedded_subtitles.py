from douyin.models import VideoInfo
from douyin.services.embedded_subtitles import extract_embedded_transcript


def test_extracts_video_text_segments():
    video = VideoInfo(
        source_url="https://v.douyin.com/a/",
        resolved_url="https://www.douyin.com/video/1",
        media_url="https://media.example/video.mp4",
        duration_ms=5000,
        raw={
            "video_text": [
                {"start_time": 0, "end_time": 1200, "text": "First line"},
                {"start_time": 1200, "end_time": 2500, "text": "Second line"},
            ]
        },
    )

    transcript = extract_embedded_transcript(video)

    assert transcript is not None
    assert transcript.engine == "embedded"
    assert transcript.text == "First line\nSecond line"
    assert [item.text for item in transcript.segments] == ["First line", "Second line"]


def test_ignores_plain_description_without_subtitle_fields():
    video = VideoInfo(
        source_url="https://v.douyin.com/a/",
        resolved_url="https://www.douyin.com/video/1",
        media_url="https://media.example/video.mp4",
        raw={"desc": "This is only a video caption, not timed subtitles."},
    )

    assert extract_embedded_transcript(video) is None
