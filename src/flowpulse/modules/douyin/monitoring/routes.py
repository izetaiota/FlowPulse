"""抖音平台 API：账号接入（T3.1）+ 作品监控（T3.3）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from flowpulse.modules.douyin.account import DouyinAccountService
from flowpulse.modules.douyin.monitoring.service import DouyinMonitorService
from flowpulse.modules.platforms import MonitorScheduler

router = APIRouter(prefix="/api/v1/douyin", tags=["douyin"])


def get_douyin_account_service() -> DouyinAccountService:
    raise RuntimeError("Dependency override is not configured")


def get_douyin_monitor_service() -> DouyinMonitorService:
    raise RuntimeError("Dependency override is not configured")


def get_douyin_monitor_scheduler() -> MonitorScheduler:
    raise RuntimeError("Dependency override is not configured")


# ---- 账号（T3.1） ----


class CookieImportRequest(BaseModel):
    cookie: str = Field(min_length=1, max_length=65536)


@router.get("/account/status")
def account_status(service: DouyinAccountService = Depends(get_douyin_account_service)) -> dict:
    return service.status()


@router.post("/account/cookie")
def import_cookie(
    request: CookieImportRequest, service: DouyinAccountService = Depends(get_douyin_account_service)
) -> dict:
    try:
        return service.import_cookie(request.cookie)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/account")
def clear_account(
    service: DouyinAccountService = Depends(get_douyin_account_service),
) -> dict:
    return service.clear()


@router.post("/account/qr-login")
async def qr_login_start(
    service: DouyinAccountService = Depends(get_douyin_account_service),
) -> dict:
    try:
        return await service.qr_start()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/account/qr-login/{session_id}")
def qr_login_poll(
    session_id: str, service: DouyinAccountService = Depends(get_douyin_account_service)
) -> dict:
    return service.qr_poll(session_id)


@router.delete("/account/qr-login/{session_id}")
def qr_login_cancel(
    session_id: str, service: DouyinAccountService = Depends(get_douyin_account_service)
) -> dict:
    return service.qr_cancel(session_id)


# ---- 作品监控（T3.3） ----


class MonitorCreate(BaseModel):
    kind: str = Field(pattern="^(creator|keyword)$")
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
def list_monitors(service: DouyinMonitorService = Depends(get_douyin_monitor_service)) -> dict:
    return {"monitors": service.list_with_stats()}


@router.post("/monitoring/monitors", status_code=201)
def create_monitor(
    request: MonitorCreate, service: DouyinMonitorService = Depends(get_douyin_monitor_service)
) -> dict:
    target = request.target.strip()
    if request.kind == "creator" and "douyin.com" not in target and not target.startswith("MS4W"):
        # 允许裸 sec_uid（MS4W 开头）或完整主页链接
        if len(target) < 20:
            raise HTTPException(status_code=400, detail="创作者监控需提供抖音主页链接或 sec_uid")
    monitor = service.repository.create_monitor(
        {
            "kind": request.kind,
            "target": target,
            "name": request.name.strip() or target,
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
    service: DouyinMonitorService = Depends(get_douyin_monitor_service),
) -> dict:
    if service.repository.get_monitor(monitor_id) is None:
        raise HTTPException(status_code=404, detail="监控目标不存在")
    updated = service.repository.update_monitor(
        monitor_id, request.model_dump(exclude_none=True)
    )
    return {
        **(updated or {}),
        "content_count": service.repository.content_stats().get(monitor_id, 0),
    }


@router.delete("/monitoring/monitors/{monitor_id}")
def delete_monitor(
    monitor_id: int, service: DouyinMonitorService = Depends(get_douyin_monitor_service)
) -> dict:
    if not service.repository.delete_monitor(monitor_id):
        raise HTTPException(status_code=404, detail="监控目标不存在")
    return {"deleted": True}


@router.post("/monitoring/monitors/{monitor_id}/scan")
async def scan_monitor(
    monitor_id: int, service: DouyinMonitorService = Depends(get_douyin_monitor_service)
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
    service: DouyinMonitorService = Depends(get_douyin_monitor_service),
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
    scheduler: MonitorScheduler = Depends(get_douyin_monitor_scheduler),
) -> dict:
    return scheduler.status()
