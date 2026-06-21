from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(StrEnum):
    PENDING = "pending"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoInfo(BaseModel):
    aweme_id: str | None = None
    source_url: str
    resolved_url: str
    media_url: str
    title: str = "Untitled Douyin video"
    author: str | None = None
    cover_url: str | None = None
    duration_ms: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class TranscriptSegment(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class Transcript(BaseModel):
    engine: str
    language: str | None = None
    text: str
    segments: list[TranscriptSegment] = Field(default_factory=list)


class Artifact(BaseModel):
    name: str
    media_type: str
    size: int


class TranscribeRequest(BaseModel):
    input: str = Field(min_length=1)
    engine: Literal["auto", "mock", "whisper", "sensevoice", "tingwu", "openai"] = "auto"
    formats: list[Literal["json", "srt", "markdown"]] = Field(
        default_factory=lambda: ["json", "srt", "markdown"]
    )
    keep_video: bool = False


class TaskRecord(BaseModel):
    id: str
    request: TranscribeRequest
    status: TaskStatus = TaskStatus.PENDING
    progress: int = Field(default=0, ge=0, le=100)
    message: str = ""
    error: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def task_dir(self, root: Path) -> Path:
        return root / "tasks" / self.id
