import json
from pathlib import Path

from douyin_transcribe.models import Artifact, Transcript, TranscriptSegment, VideoInfo


def render_artifacts(
    directory: Path,
    video: VideoInfo,
    transcript: Transcript,
    formats: list[str],
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    source_path = directory / "source.json"
    source_path.write_text(video.model_dump_json(indent=2), encoding="utf-8")
    artifacts.append(to_artifact(source_path, "application/json"))

    transcript_path = directory / "transcript.json"
    transcript_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    if "json" in formats:
        artifacts.append(to_artifact(transcript_path, "application/json"))
    if "srt" in formats:
        path = directory / "transcript.srt"
        path.write_text(render_srt(transcript), encoding="utf-8")
        artifacts.append(to_artifact(path, "application/x-subrip"))
    if "markdown" in formats:
        path = directory / "notes.md"
        path.write_text(render_markdown(video, transcript), encoding="utf-8")
        artifacts.append(to_artifact(path, "text/markdown"))
    return artifacts


def render_srt(transcript: Transcript) -> str:
    segments = transcript.segments
    if not segments and transcript.text:
        segments = [TranscriptSegment(start_ms=0, end_ms=5000, text=transcript.text)]
    return "\n".join(
        f"{index}\n{timestamp(item.start_ms)} --> {timestamp(item.end_ms)}\n{item.text}\n"
        for index, item in enumerate(segments, start=1)
    )


def timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def render_markdown(video: VideoInfo, transcript: Transcript) -> str:
    frontmatter = {
        "aweme_id": video.aweme_id,
        "source_url": video.source_url,
        "author": video.author,
        "transcriber": transcript.engine,
    }
    yaml_lines = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items()
    )
    return f"---\n{yaml_lines}\n---\n\n# {video.title}\n\n## Transcript\n\n{transcript.text}\n"


def to_artifact(path: Path, media_type: str) -> Artifact:
    return Artifact(name=path.name, media_type=media_type, size=path.stat().st_size)
