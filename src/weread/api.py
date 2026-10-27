"""微信读书采集模块的 REST API。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from weread.client import WereadAPIError
from weread.models import (
    CredentialUpdateRequest,
    MpArticle,
    MpSubscription,
    SubscriptionCreateRequest,
    SubscriptionSyncResult,
    SyncSummary,
)
from weread.rss import build_rss
from weread.scheduler import WereadScheduler
from weread.service import WereadService

router = APIRouter()


def get_weread_service() -> WereadService:
    raise RuntimeError("Dependency override is not configured")


def get_weread_scheduler() -> WereadScheduler:
    raise RuntimeError("Dependency override is not configured")


def _mask_cookie(cookie: str) -> str:
    if len(cookie) <= 24:
        return cookie[:8] + "..."
    return f"{cookie[:24]}...（长度 {len(cookie)}）"


def _translate_error(exc: WereadAPIError) -> HTTPException:
    if exc.kind == "auth":
        return HTTPException(status_code=401, detail=f"微信读书登录态问题：{exc.message}")
    if exc.kind == "rate_limit":
        return HTTPException(status_code=429, detail=f"触发频率限制：{exc.message}")
    return HTTPException(status_code=502, detail=f"微信读书接口异常：{exc.message}")


# ---- 凭证 ----


@router.post("/api/weread/credential")
async def save_credential(
    request: CredentialUpdateRequest, service: WereadService = Depends(get_weread_service)
) -> dict:
    if not request.cookie.strip():
        raise HTTPException(status_code=400, detail="Cookie 不能为空")
    try:
        return await service.save_credential(request.cookie)
    except WereadAPIError as exc:
        raise _translate_error(exc) from exc


@router.get("/api/weread/credential")
async def credential_status(service: WereadService = Depends(get_weread_service)) -> dict:
    state = service.repository.get_credential()
    if not state:
        return {"configured": False}
    return {
        "configured": True,
        "masked_cookie": _mask_cookie(state.cookie),
        "saved_at": state.saved_at,
        "last_validated_at": state.last_validated_at,
        "valid": state.valid,
        "last_error": state.last_error,
    }


@router.delete("/api/weread/credential")
async def delete_credential(service: WereadService = Depends(get_weread_service)) -> dict:
    return {"deleted": service.repository.delete_credential()}


@router.post("/api/weread/credential/validate")
async def validate_credential(service: WereadService = Depends(get_weread_service)) -> dict:
    try:
        return await service.validate_current_credential()
    except WereadAPIError as exc:
        raise _translate_error(exc) from exc


# ---- 订阅 ----


@router.get("/api/weread/subscriptions", response_model=list[MpSubscription])
async def list_subscriptions(service: WereadService = Depends(get_weread_service)) -> list[MpSubscription]:
    return service.list_subscriptions()


@router.post("/api/weread/subscriptions", response_model=MpSubscription, status_code=201)
async def add_subscription(
    request: SubscriptionCreateRequest, service: WereadService = Depends(get_weread_service)
) -> MpSubscription:
    try:
        sub = await service.add_subscription(request.input)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WereadAPIError as exc:
        raise _translate_error(exc) from exc
    return sub


@router.delete("/api/weread/subscriptions/{book_id}")
async def delete_subscription(
    book_id: str, service: WereadService = Depends(get_weread_service)
) -> dict:
    if not service.delete_subscription(book_id):
        raise HTTPException(status_code=404, detail="订阅不存在")
    return {"deleted": True}


@router.get("/api/weread/subscriptions/{book_id}/articles")
async def list_articles(
    book_id: str,
    service: WereadService = Depends(get_weread_service),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> dict:
    if not service.repository.get_subscription(book_id):
        raise HTTPException(status_code=404, detail="订阅不存在")
    page, next_cursor = service.list_articles(book_id, limit, cursor)
    return {
        "book_id": book_id,
        "count": len(page),
        "next_cursor": next_cursor,
        "items": [item.model_dump() for item in page],
    }


# ---- 同步与总览 ----


@router.post("/api/weread/sync", response_model=SyncSummary)
async def sync_all(service: WereadService = Depends(get_weread_service)) -> SyncSummary:
    try:
        return await service.sync_all()
    except WereadAPIError as exc:
        raise _translate_error(exc) from exc


@router.post("/api/weread/subscriptions/{book_id}/sync", response_model=SubscriptionSyncResult)
async def sync_one(
    book_id: str, service: WereadService = Depends(get_weread_service)
) -> SubscriptionSyncResult:
    if not service.repository.get_subscription(book_id):
        raise HTTPException(status_code=404, detail="订阅不存在")
    return await service.sync_subscription(book_id)


@router.get("/api/weread/status")
async def overall_status(service: WereadService = Depends(get_weread_service)) -> dict:
    credential = service.repository.get_credential()
    subs = service.list_subscriptions()
    return {
        "credential": {
            "configured": bool(credential),
            "valid": credential.valid if credential else None,
            "last_validated_at": credential.last_validated_at if credential else None,
        },
        "subscriptions": [
            {
                "book_id": s.book_id,
                "name": s.name,
                "last_sync_at": s.last_sync_at,
                "last_sync_status": s.last_sync_status,
                "article_count": s.article_count,
            }
            for s in subs
        ],
    }


# ---- RSS 输出 ----


def _rss_response(xml: str) -> Response:
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/api/weread/rss/all.xml")
async def rss_all(
    request: Request, service: WereadService = Depends(get_weread_service)
) -> Response:
    base = str(request.base_url).rstrip("/")
    articles = []
    for sub in service.list_subscriptions():
        articles.extend(service.repository.list_articles(sub.book_id))
    articles.sort(key=lambda a: (a.publish_time, a.created_at), reverse=True)
    xml = build_rss(
        "心流 FlowPulse · 公众号订阅（全部）",
        base,
        "全部订阅公众号文章合并输出",
        articles[:100],
    )
    return _rss_response(xml)


@router.get("/api/weread/rss/{book_id}.xml")
async def rss_one(
    book_id: str,
    request: Request,
    service: WereadService = Depends(get_weread_service),
) -> Response:
    sub = service.repository.get_subscription(book_id)
    if not sub:
        raise HTTPException(status_code=404, detail="订阅不存在")
    base = str(request.base_url).rstrip("/")
    xml = build_rss(
        f"心流 FlowPulse · {sub.name or book_id}",
        base,
        f"公众号「{sub.name or book_id}」最新文章",
        service.repository.list_articles(book_id)[:100],
    )
    return _rss_response(xml)


# ---- 调度器 ----


@router.get("/api/weread/scheduler")
async def scheduler_status(
    scheduler: WereadScheduler = Depends(get_weread_scheduler),
) -> dict:
    return scheduler.status()


@router.post("/api/weread/scheduler/trigger")
async def scheduler_trigger(
    scheduler: WereadScheduler = Depends(get_weread_scheduler),
) -> dict:
    """手动触发一次调度（与定时循环同路径，含告警与状态记录）。"""
    return await scheduler.run_once()
