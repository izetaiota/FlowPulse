from __future__ import annotations

from typing import Any

from douyin.models import Transcript, TranscriptSegment, VideoInfo

SUBTITLE_BRANCH_KEYS = (
    "caption",
    "subtitle",
    "sub_title",
    "video_text",
    "ocr",
    "asr",
    "transcript",
)

TEXT_KEYS = (
    "text",
    "content",
    "caption_text",
    "subtitle_text",
    "sentence",
    "words",
    "utterance_text",
)

START_KEYS = ("start_ms", "start_time", "start", "begin_time", "begin", "from")
END_KEYS = ("end_ms", "end_time", "end", "stop_time", "stop", "to")


def extract_embedded_transcript(video: VideoInfo) -> Transcript | None:
    raw = video.raw or {}
    branches = list(find_subtitle_branches(raw))
    segments: list[TranscriptSegment] = []
    texts: list[str] = []

    for branch in branches:
        branch_segments = collect_segments(branch, video.duration_ms)
        segments.extend(branch_segments)
        if not branch_segments:
            text = collect_text(branch)
            if text:
                texts.append(text)

    deduped_segments = dedupe_segments(segments)
    if deduped_segments:
        text = "\n".join(segment.text for segment in deduped_segments)
        return Transcript(engine="embedded", language=None, text=text, segments=deduped_segments)

    deduped_text = "\n".join(dict.fromkeys(item for item in texts if item))
    if deduped_text:
        end_ms = video.duration_ms or 5000
        return Transcript(
            engine="embedded",
            language=None,
            text=deduped_text,
            segments=[TranscriptSegment(start_ms=0, end_ms=end_ms, text=deduped_text)],
        )

    return None


def find_subtitle_branches(value: Any) -> list[Any]:
    branches: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if any(marker in lowered for marker in SUBTITLE_BRANCH_KEYS):
                branches.append(item)
            branches.extend(find_subtitle_branches(item))
    elif isinstance(value, list):
        for item in value:
            branches.extend(find_subtitle_branches(item))
    return branches


def collect_segments(value: Any, duration_ms: int | None) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    if isinstance(value, dict):
        text = first_text(value)
        if text:
            start_ms = first_time(value, START_KEYS)
            end_ms = first_time(value, END_KEYS)
            if start_ms is not None or end_ms is not None:
                start = normalize_time(start_ms, 0)
                end = normalize_time(end_ms, duration_ms or max(start + 3000, 5000))
                if end <= start:
                    end = start + 3000
                segments.append(TranscriptSegment(start_ms=start, end_ms=end, text=text))
        for item in value.values():
            segments.extend(collect_segments(item, duration_ms))
    elif isinstance(value, list):
        for item in value:
            segments.extend(collect_segments(item, duration_ms))
    return segments


def collect_text(value: Any) -> str:
    texts: list[str] = []
    if isinstance(value, str):
        text = clean_text(value)
        if text:
            texts.append(text)
    elif isinstance(value, dict):
        text = first_text(value)
        if text:
            texts.append(text)
        for item in value.values():
            nested = collect_text(item)
            if nested:
                texts.append(nested)
    elif isinstance(value, list):
        for item in value:
            nested = collect_text(item)
            if nested:
                texts.append(nested)
    return "\n".join(dict.fromkeys(texts))


def first_text(value: dict[str, Any]) -> str:
    for key in TEXT_KEYS:
        item = value.get(key)
        if isinstance(item, str):
            text = clean_text(item)
            if text:
                return text
    return ""


def first_time(value: dict[str, Any], keys: tuple[str, ...]) -> int | float | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, (int, float)):
            return item
    return None


def normalize_time(value: int | float | None, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, float) and not value.is_integer():
        return int(value * 1000)
    return int(value)


def dedupe_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    seen: set[tuple[int, int, str]] = set()
    result: list[TranscriptSegment] = []
    for segment in sorted(segments, key=lambda item: (item.start_ms, item.end_ms, item.text)):
        key = (segment.start_ms, segment.end_ms, segment.text)
        if key in seen:
            continue
        seen.add(key)
        result.append(segment)
    return result


def clean_text(value: str) -> str:
    return " ".join(value.replace("\r", "\n").split()).strip()
