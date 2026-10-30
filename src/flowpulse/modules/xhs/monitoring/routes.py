"""小红书作品监控 API：/api/v1/xhs/monitoring（目标 CRUD / 立即扫描 / 作品分页 / 调度状态）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from flowpulse.modules.xhs.monitoring.scheduler import XhsMonitorScheduler
from flowpulse.modules.xhs.monitoring.service import XhsMonitorService

router = APIRouter(prefix="/api/v1/xhs/monitoring", tags=["xhs-monitoring"])


def get_monitor_service() -> XhsMonitorService:
    raise RuntimeError("Dependency override is not configured")


def get_monitor_scheduler() -> XhsMonitorScheduler:
    raise RuntimeError("Dependency override is not configured")


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


@router.get("/monitors")
def list_monitors(service: XhsMonitorService = Depends(get_monitor_service)) -> dict:
    return {"monitors": service.list_with_stats()}


@router.post("/monitors", status_code=201)
def create_monitor(
    request: MonitorCreate, service: XhsMonitorService = Depends(get_monitor_service)
) -> dict:
    target = request.target.strip()
    if request.kind == "creator" and "xiaohongshu.com" not in target:
        raise HTTPException(status_code=400, detail="创作者监控需粘贴小红书用户主页链接")
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


@router.patch("/monitors/{monitor_id}")
def update_monitor(
    monitor_id: int,
    request: MonitorUpdate,
    service: XhsMonitorService = Depends(get_monitor_service),
) -> dict:
    if service.repository.get_monitor(monitor_id) is None:
        raise HTTPException(status_code=404, detail="监控目标不存在")
    updated = service.repository.update_monitor(monitor_id, request.model_dump(exclude_none=True))
    return {
        **(updated or {}),
        "content_count": service.repository.content_stats().get(monitor_id, 0),
    }


@router.delete("/monitors/{monitor_id}")
def delete_monitor(
    monitor_id: int, service: XhsMonitorService = Depends(get_monitor_service)
) -> dict:
    if not service.repository.delete_monitor(monitor_id):
        raise HTTPException(status_code=404, detail="监控目标不存在")
    return {"deleted": True}


@router.post("/monitors/{monitor_id}/scan")
async def scan_monitor(
    monitor_id: int, service: XhsMonitorService = Depends(get_monitor_service)
) -> dict:
    monitor = service.repository.get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="监控目标不存在")
    result = await service.scan_monitor(monitor)
    return {"result": result, "monitor": service.repository.get_monitor(monitor_id)}


@router.get("/contents")
def list_contents(
    monitor_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    service: XhsMonitorService = Depends(get_monitor_service),
) -> dict:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    contents, total = service.repository.list_contents(monitor_id, page, page_size)
    names = {m["id"]: (m.get("name") or m["target"]) for m in service.repository.list_monitors()}
    for content in contents:
        content["monitor_name"] = names.get(content.get("monitor_id"), "")
    return {"contents": contents, "total": total, "page": page, "page_size": page_size}


@router.get("/status")
def scheduler_status(
    scheduler: XhsMonitorScheduler = Depends(get_monitor_scheduler),
) -> dict:
    return scheduler.status()
