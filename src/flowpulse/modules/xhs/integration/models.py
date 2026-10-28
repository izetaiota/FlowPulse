from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


Platform = Literal["pc", "creator"]
SaveChoice = Literal["all", "media", "media-image", "media-video", "excel"]


# --- Login ---------------------------------------------------------------


class CookieLoginRequest(BaseModel):
    platform: Platform = "pc"
    cookies: str = Field(min_length=1)


class QrcodeStartRequest(BaseModel):
    platform: Platform = "pc"


class QrcodeStartResponse(BaseModel):
    session_id: str
    platform: Platform
    qr_url: str
    qr_image_base64: str


class QrcodePollResponse(BaseModel):
    session_id: str
    platform: Platform
    status: Literal["waiting", "scanned", "confirmed", "expired", "error"]
    message: str
    logged_in: bool = False


class PhoneCodeRequest(BaseModel):
    platform: Platform = "pc"
    phone: str = Field(min_length=1)
    zone: str = "86"


class PhoneCodeResponse(BaseModel):
    session_id: str
    platform: Platform
    message: str


class PhoneVerifyRequest(BaseModel):
    session_id: str
    code: str = Field(min_length=1)


class LoginStatus(BaseModel):
    platform: Platform
    logged_in: bool
    user_id: str | None = None
    message: str = ""


# --- Data (synchronous, quick) ------------------------------------------


class NoteDetailRequest(BaseModel):
    url: str = Field(min_length=1)


class UserNotesRequest(BaseModel):
    user_url: str = Field(min_length=1)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    require_num: int = Field(default=10, ge=1, le=1000)
    sort_type_choice: int = 0
    note_type: int = 0
    note_time: int = 0
    note_range: int = 0
    pos_distance: int = 0
    geo: dict[str, Any] | None = None


class CommentsRequest(BaseModel):
    url: str = Field(min_length=1)


class UserInfoRequest(BaseModel):
    user_id: str = Field(min_length=1)


class SearchUserRequest(BaseModel):
    query: str = Field(min_length=1)
    require_num: int = Field(default=10, ge=1, le=1000)


class HomefeedRequest(BaseModel):
    category: str = "homefeed_recommend"
    require_num: int = Field(default=20, ge=1, le=1000)


class KeywordRequest(BaseModel):
    word: str = Field(min_length=1)


class NoWaterVideoRequest(BaseModel):
    note_id: str = Field(min_length=1)


class NoWaterImageRequest(BaseModel):
    img_url: str = Field(min_length=1)


# --- Creator: read + publish --------------------------------------------


class KeywordSearchRequest(BaseModel):
    keyword: str = Field(min_length=1)


class UploadMediaRequest(BaseModel):
    path: str = Field(min_length=1)
    media_type: str = "image"


class PostNoteRequest(BaseModel):
    note_info: dict[str, Any]


# --- PuGongYing (蒲公英) / QianFan (千帆) --------------------------------


class PgyCategoriesRequest(BaseModel):
    cookies: str | None = None


class PgyUsersRequest(BaseModel):
    num: int = Field(default=10, ge=1, le=1000)
    content_tag: str | None = None
    cookies: str | None = None


class PgyUserRequest(BaseModel):
    user_id: str = Field(min_length=1)
    cookies: str | None = None


class QianfanCategoriesRequest(BaseModel):
    cookies: str | None = None


class QianfanUsersRequest(BaseModel):
    choice: str = "-1"
    num: int = Field(default=10, ge=1, le=1000)
    cookies: str | None = None


class QianfanUserRequest(BaseModel):
    user_id: str = Field(min_length=1)
    cookies: str | None = None


class DataResponse(BaseModel):
    success: bool
    message: str
    data: Any = None


# --- Async download / export jobs ---------------------------------------


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(StrEnum):
    NOTES = "notes"
    USER = "user"
    SEARCH = "search"


class CreateJobRequest(BaseModel):
    type: JobType
    save_choice: SaveChoice = "all"
    excel_name: str = ""
    # NOTES
    notes: list[str] = Field(default_factory=list)
    # USER
    user_url: str = ""
    # SEARCH
    query: str = ""
    require_num: int = Field(default=10, ge=1, le=1000)
    sort_type_choice: int = 0
    note_type: int = 0
    note_time: int = 0
    note_range: int = 0
    pos_distance: int = 0
    geo: dict[str, Any] | None = None


class JobRecord(BaseModel):
    id: str
    type: JobType
    request: CreateJobRequest
    status: JobStatus = JobStatus.PENDING
    message: str = ""
    error: str | None = None
    note_count: int = 0
    artifacts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
