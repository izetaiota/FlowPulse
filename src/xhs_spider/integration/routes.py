from __future__ import annotations

import base64
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from xhs_spider.integration.models import (
    CommentsRequest,
    CookieLoginRequest,
    CreateJobRequest,
    DataResponse,
    HomefeedRequest,
    JobRecord,
    KeywordRequest,
    KeywordSearchRequest,
    LoginStatus,
    NoteDetailRequest,
    NoWaterImageRequest,
    NoWaterVideoRequest,
    PgyCategoriesRequest,
    PgyUserRequest,
    PgyUsersRequest,
    PhoneCodeRequest,
    PhoneCodeResponse,
    PhoneVerifyRequest,
    Platform,
    PostNoteRequest,
    QianfanCategoriesRequest,
    QianfanUserRequest,
    QianfanUsersRequest,
    QrcodePollResponse,
    QrcodeStartRequest,
    QrcodeStartResponse,
    SearchRequest,
    SearchUserRequest,
    UploadMediaRequest,
    UserInfoRequest,
    UserNotesRequest,
)
from xhs_spider.integration.service import XhsService

router = APIRouter(prefix="/api/v1/xhs", tags=["xhs"])


def get_xhs_service() -> XhsService:
    raise RuntimeError("Dependency override is not configured")


def _qr_png_base64(qr_url: str) -> str:
    import qrcode

    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# --- login ---------------------------------------------------------------


@router.post("/login/cookie", response_model=LoginStatus)
async def login_cookie(
    request: CookieLoginRequest, service: XhsService = Depends(get_xhs_service)
) -> LoginStatus:
    return await service.login_cookie(request.platform, request.cookies)


@router.get("/login/status", response_model=LoginStatus)
async def login_status(
    platform: Platform = "pc", service: XhsService = Depends(get_xhs_service)
) -> LoginStatus:
    return await service.login_status(platform)


@router.post("/login/qrcode", response_model=QrcodeStartResponse)
async def qrcode_start(
    request: QrcodeStartRequest, service: XhsService = Depends(get_xhs_service)
) -> QrcodeStartResponse:
    try:
        session_id, qr_url = await service.qrcode_start(request.platform)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    if qr_url is None:
        raise HTTPException(409, "检测到可复用会话，已直接登录，无需二维码")
    return QrcodeStartResponse(
        session_id=session_id,
        platform=request.platform,
        qr_url=qr_url,
        qr_image_base64=_qr_png_base64(qr_url),
    )


@router.get("/login/qrcode/{session_id}", response_model=QrcodePollResponse)
async def qrcode_poll(
    session_id: str, service: XhsService = Depends(get_xhs_service)
) -> QrcodePollResponse:
    status, message, logged_in = await service.qrcode_poll(session_id)
    # platform is unknown here without the session; report best-effort.
    session = service.sessions.get(session_id)
    platform = session["platform"] if session else "pc"
    return QrcodePollResponse(
        session_id=session_id,
        platform=platform,
        status=status,
        message=message,
        logged_in=logged_in,
    )


@router.post("/login/phone/code", response_model=PhoneCodeResponse)
async def phone_send(
    request: PhoneCodeRequest, service: XhsService = Depends(get_xhs_service)
) -> PhoneCodeResponse:
    try:
        session_id, message = await service.phone_send(
            request.platform, request.phone, request.zone
        )
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return PhoneCodeResponse(session_id=session_id, platform=request.platform, message=message)


@router.post("/login/phone/verify", response_model=LoginStatus)
async def phone_verify(
    request: PhoneVerifyRequest, service: XhsService = Depends(get_xhs_service)
) -> LoginStatus:
    try:
        return await service.phone_verify(request.session_id, request.code)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


# --- data (quick) --------------------------------------------------------


@router.post("/notes/detail", response_model=DataResponse)
async def note_detail(
    request: NoteDetailRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.note_detail(request.url)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/notes/comments", response_model=DataResponse)
async def note_comments(
    request: CommentsRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.comments(request.url)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/users/notes", response_model=DataResponse)
async def user_notes(
    request: UserNotesRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.user_notes(request.user_url)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/search", response_model=DataResponse)
async def search(
    request: SearchRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.search(request)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/creator/posted-notes", response_model=DataResponse)
async def creator_posted_notes(
    service: XhsService = Depends(get_xhs_service),
) -> DataResponse:
    ok, msg, data = await service.creator_posted_notes()
    return DataResponse(success=ok, message=str(msg), data=data)


# --- PC read-only extras -------------------------------------------------


@router.post("/users/info", response_model=DataResponse)
async def user_info(
    request: UserInfoRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.user_info(request.user_id)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/users/like-notes", response_model=DataResponse)
async def user_like_notes(
    request: UserNotesRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.user_like_notes(request.user_url)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/users/collect-notes", response_model=DataResponse)
async def user_collect_notes(
    request: UserNotesRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.user_collect_notes(request.user_url)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/search/users", response_model=DataResponse)
async def search_users(
    request: SearchUserRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.search_users(request.query, request.require_num)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/search/keyword", response_model=DataResponse)
async def search_keyword(
    request: KeywordRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.search_keyword(request.word)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/homefeed", response_model=DataResponse)
async def homefeed(
    request: HomefeedRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.homefeed(request.category, request.require_num)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.get("/homefeed/channels", response_model=DataResponse)
async def homefeed_channels(service: XhsService = Depends(get_xhs_service)) -> DataResponse:
    ok, msg, data = await service.homefeed_channels()
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/notes/no-water-video", response_model=DataResponse)
async def no_water_video(
    request: NoWaterVideoRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.no_water_video(request.note_id)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/notes/no-water-image", response_model=DataResponse)
async def no_water_image(
    request: NoWaterImageRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.no_water_image(request.img_url)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.get("/messages/unread", response_model=DataResponse)
async def messages_unread(service: XhsService = Depends(get_xhs_service)) -> DataResponse:
    ok, msg, data = await service.unread_message()
    return DataResponse(success=ok, message=str(msg), data=data)


@router.get("/messages/mentions", response_model=DataResponse)
async def messages_mentions(service: XhsService = Depends(get_xhs_service)) -> DataResponse:
    ok, msg, data = await service.mentions()
    return DataResponse(success=ok, message=str(msg), data=data)


@router.get("/messages/likes-collects", response_model=DataResponse)
async def messages_likes_collects(service: XhsService = Depends(get_xhs_service)) -> DataResponse:
    ok, msg, data = await service.likes_and_collects()
    return DataResponse(success=ok, message=str(msg), data=data)


@router.get("/messages/connections", response_model=DataResponse)
async def messages_connections(service: XhsService = Depends(get_xhs_service)) -> DataResponse:
    ok, msg, data = await service.new_connections()
    return DataResponse(success=ok, message=str(msg), data=data)


# --- Creator read + publish ---------------------------------------------


@router.get("/creator/user-info", response_model=DataResponse)
async def creator_user_info(service: XhsService = Depends(get_xhs_service)) -> DataResponse:
    ok, msg, data = await service.creator_user_info()
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/creator/topic", response_model=DataResponse)
async def creator_topic(
    request: KeywordSearchRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.creator_topic(request.keyword)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/creator/location", response_model=DataResponse)
async def creator_location(
    request: KeywordSearchRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.creator_location(request.keyword)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/creator/upload-media", response_model=DataResponse)
async def creator_upload_media(
    request: UploadMediaRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.creator_upload_media(request.path, request.media_type)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/creator/post-note", response_model=DataResponse)
async def creator_post_note(
    request: PostNoteRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.creator_post_note(request.note_info)
    return DataResponse(success=ok, message=str(msg), data=data)


# --- PuGongYing (蒲公英) -------------------------------------------------


@router.post("/pgy/categories", response_model=DataResponse)
async def pgy_categories(
    request: PgyCategoriesRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.pgy_categories(request.cookies)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/pgy/users", response_model=DataResponse)
async def pgy_users(
    request: PgyUsersRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.pgy_users(request.num, request.content_tag, request.cookies)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/pgy/user-detail", response_model=DataResponse)
async def pgy_user_detail(
    request: PgyUserRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.pgy_user_detail(request.user_id, request.cookies)
    return DataResponse(success=ok, message=str(msg), data=data)


# --- QianFan (千帆) ------------------------------------------------------


@router.post("/qianfan/categories", response_model=DataResponse)
async def qianfan_categories(
    request: QianfanCategoriesRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.qianfan_categories(request.cookies)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/qianfan/users", response_model=DataResponse)
async def qianfan_users(
    request: QianfanUsersRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.qianfan_users(request.choice, request.num, request.cookies)
    return DataResponse(success=ok, message=str(msg), data=data)


@router.post("/qianfan/user-detail", response_model=DataResponse)
async def qianfan_user_detail(
    request: QianfanUserRequest, service: XhsService = Depends(get_xhs_service)
) -> DataResponse:
    ok, msg, data = await service.qianfan_user_detail(request.user_id, request.cookies)
    return DataResponse(success=ok, message=str(msg), data=data)


# --- async download / export jobs ---------------------------------------


@router.post("/jobs", response_model=JobRecord, status_code=202)
async def create_job(
    request: CreateJobRequest, service: XhsService = Depends(get_xhs_service)
) -> JobRecord:
    return service.create_job(request)


@router.get("/jobs", response_model=list[JobRecord])
async def list_jobs(service: XhsService = Depends(get_xhs_service)) -> list[JobRecord]:
    return service.jobs.list()


@router.get("/jobs/{job_id}", response_model=JobRecord)
async def get_job(job_id: str, service: XhsService = Depends(get_xhs_service)) -> JobRecord:
    record = service.jobs.get(job_id)
    if not record:
        raise HTTPException(404, "Job not found")
    return record


@router.get("/jobs/{job_id}/artifacts/{path:path}")
async def download_job_artifact(
    job_id: str, path: str, service: XhsService = Depends(get_xhs_service)
):
    record = service.jobs.get(job_id)
    if not record:
        raise HTTPException(404, "Job not found")
    job_dir = service.jobs.job_dir(job_id).resolve()
    target = (job_dir / path).resolve()
    if job_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "Artifact not found")
    return FileResponse(target, filename=target.name)
