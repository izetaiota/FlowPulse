"""抖音发布 API（T3.4）：/api/v1/douyin/publish（草稿 CRUD / 提交 / 取消 / 媒体清单）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from flowpulse.modules.douyin.publish.service import DouyinPublishService

router = APIRouter(prefix="/api/v1/douyin/publish", tags=["douyin-publish"])


def get_douyin_publish_service() -> DouyinPublishService:
    raise RuntimeError("Dependency override is not configured")


class PublishDraftRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    desc: str = Field(default="", max_length=2000)
    topics: str = Field(default="", max_length=500)
    media_paths: list[str] = Field(min_length=1, max_length=9)
    media_type: str = Field(default="video", pattern="^(video|images)$")
    visibility: str = Field(default="public", pattern="^(public|friends|private)$")
    allow_save: bool = True


@router.get("")
def list_tasks(service: DouyinPublishService = Depends(get_douyin_publish_service)) -> dict:
    return {"tasks": service.store.list()}


@router.get("/media-files")
def list_media_files(
    service: DouyinPublishService = Depends(get_douyin_publish_service),
) -> dict:
    return {"files": service.list_media_files()}


@router.post("", status_code=201)
def create_draft(
    request: PublishDraftRequest, service: DouyinPublishService = Depends(get_douyin_publish_service)
) -> dict:
    try:
        return service.create_draft(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/submit")
def submit_task(
    task_id: int, service: DouyinPublishService = Depends(get_douyin_publish_service)
) -> dict:
    try:
        return service.submit(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: int, service: DouyinPublishService = Depends(get_douyin_publish_service)
) -> dict:
    try:
        return service.cancel(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{task_id}")
def delete_task(
    task_id: int, service: DouyinPublishService = Depends(get_douyin_publish_service)
) -> dict:
    try:
        if not service.delete(task_id):
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"deleted": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
