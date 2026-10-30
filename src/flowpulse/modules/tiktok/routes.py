"""TikTok API（T5.3）：账号（Cookie 导入）+ 关键词监控 + 搜索/评论直连。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from flowpulse.modules.platforms import MonitorScheduler
from flowpulse.modules.tiktok.account import TiktokAccountService
from flowpulse.modules.tiktok.fetcher import TiktokFetcher
from flowpulse.modules.tiktok.monitoring.service import TiktokMonitorService

router = APIRouter(prefix="/api/v1/tiktok", tags=["tiktok"])


def get_tiktok_account_service() -> TiktokAccountService:
    raise RuntimeError("Dependency override is not configured")


def get_tiktok_monitor_service() -> TiktokMonitorService:
    raise RuntimeError("Dependency override is not configured")


def get_tiktok_monitor_scheduler() -> MonitorScheduler:
    raise RuntimeError("Dependency override is not configured")


def get_tiktok_fetcher() -> TiktokFetcher:
    raise RuntimeError("Dependency override is not configured")


# ---- 账号 ----


class CookieImportRequest(BaseModel):
    cookie: str = Field(min_length=1, max_length=65536)


@router.get("/account/status")
def account_status(service: TiktokAccountService = Depends(get_tiktok_account_service)) -> dict:
    return service.status()


@router.post("/account/cookie")
def import_cookie(
    request: CookieImportRequest,
    service: TiktokAccountService = Depends(get_tiktok_account_service),
) -> dict:
    try:
        return service.import_cookie(request.cookie)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/account")
def clear_account(service: TiktokAccountService = Depends(get_tiktok_account_service)) -> dict:
    return service.clear()


# ---- 直连搜索 / 评论 ----


@router.get("/search")
async def search(
    keyword: str,
    count: int = 20,
    fetcher: TiktokFetcher = Depends(get_tiktok_fetcher),
) -> dict:
    try:
        works = await fetcher.fetch_search(keyword, limit=max(1, min(50, count)))
        return {"ok": True, "works": works}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/comments")
async def comments(
    aweme_id: str,
    author_unique_id: str = "",
    count: int = 20,
    fetcher: TiktokFetcher = Depends(get_tiktok_fetcher),
) -> dict:
    try:
        items = await fetcher.fetch_comments(
            aweme_id, author_unique_id=author_unique_id, limit=max(1, min(50, count))
        )
        return {"ok": True, "comments": items}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- 关键词监控（结构同其他平台） ----


class MonitorCreate(BaseModel):
    kind: str = Field(pattern="^keyword$")  # TikTok 仅关键词（原生直连无用户作品接口）
    target: str = Field(min_length=1)
    name: str = Field(default="", max_length=255)
    interval_minutes: int = Field(default=30, ge=1, le=1440)
    include_keywords: str = Field(default="", max_length=500)
    exclude_keywords: str = Field(default="", max_length=500)
    backfill_count: int = Field(default=10, ge=0, le=100)


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    include_keywords: str | None = Field(default=None, max_length=500)
    exclude_keywords: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(active|paused)$")


@router.get("/monitoring/monitors")
def list_monitors(service: TiktokMonitorService = Depends(get_tiktok_monitor_service)) -> dict:
    return {"monitors": service.list_with_stats()}


@router.post("/monitoring/monitors", status_code=201)
def create_monitor(
    request: MonitorCreate, service: TiktokMonitorService = Depends(get_tiktok_monitor_service)
) -> dict:
    monitor = service.repository.create_monitor(
        {
            "kind": "keyword",
            "target": request.target.strip(),
            "name": request.name.strip() or request.target.strip(),
            "interval_minutes": request.interval_minutes,
            "include_keywords": request.include_keywords,
            "exclude_keywords": request.exclude_keywords,
            "backfill_count": request.backfill_count,
        }
    )
    monitor["content_count"] = 0
    return monitor


@router.patch("/monitoring/monitors/{monitor_id}")
def update_monitor(
    monitor_id: int,
    request: MonitorUpdate,
    service: TiktokMonitorService = Depends(get_tiktok_monitor_service),
) -> dict:
    if service.repository.get_monitor(monitor_id) is None:
        raise HTTPException(status_code=404, detail="监控目标不存在")
    updated = service.repository.update_monitor(monitor_id, request.model_dump(exclude_none=True))
    return {
        **(updated or {}),
        "content_count": service.repository.content_stats().get(monitor_id, 0),
    }


@router.delete("/monitoring/monitors/{monitor_id}")
def delete_monitor(
    monitor_id: int, service: TiktokMonitorService = Depends(get_tiktok_monitor_service)
) -> dict:
    if not service.repository.delete_monitor(monitor_id):
        raise HTTPException(status_code=404, detail="监控目标不存在")
    return {"deleted": True}


@router.post("/monitoring/monitors/{monitor_id}/scan")
async def scan_monitor(
    monitor_id: int, service: TiktokMonitorService = Depends(get_tiktok_monitor_service)
) -> dict:
    monitor = service.repository.get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="监控目标不存在")
    result = await service.scan_monitor(monitor)
    return {"result": result, "monitor": service.repository.get_monitor(monitor_id)}


@router.get("/monitoring/contents")
def list_contents(
    monitor_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    service: TiktokMonitorService = Depends(get_tiktok_monitor_service),
) -> dict:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    contents, total = service.repository.list_contents(monitor_id, page, page_size)
    names = {m["id"]: (m.get("name") or m["target"]) for m in service.repository.list_monitors()}
    for content in contents:
        content["monitor_name"] = names.get(content.get("monitor_id"), "")
    return {"contents": contents, "total": total, "page": page, "page_size": page_size}


@router.get("/monitoring/status")
def scheduler_status(
    scheduler: MonitorScheduler = Depends(get_tiktok_monitor_scheduler),
) -> dict:
    return scheduler.status()
