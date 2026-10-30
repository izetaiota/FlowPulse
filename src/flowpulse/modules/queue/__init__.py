"""统一任务队列视图（P0）：聚合抖音转写任务与小红书抓取任务，供前端「任务动态」展示。

只做读聚合与重试转发，不改各模块的任务模型；取消语义待底层任务支持后接入。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from flowpulse.modules.douyin.models import TaskStatus
from flowpulse.modules.douyin.services.pipeline import PipelineService
from flowpulse.modules.douyin.storage.tasks import TaskRepository

router = APIRouter(prefix="/api/v1/queue", tags=["queue"])

_KIND_LABELS = {"douyin": "抖音转写", "xhs": "小红书抓取"}


def _job_title(job: Any) -> str:
    request = job.request
    if job.type.value == "notes" and request.notes:
        return f"笔记抓取 ×{len(request.notes)}"
    if job.type.value == "user" and request.user_url:
        return f"用户主页 {request.user_url[:60]}"
    if request.query:
        return f"关键词「{request.query[:30]}」"
    return job.type.value


class QueueService:
    def __init__(self, task_repository: TaskRepository, pipeline: PipelineService, xhs_jobs):
        self.task_repository = task_repository
        self.pipeline = pipeline
        self.xhs_jobs = xhs_jobs

    def list(self, source: str | None = None) -> list[dict]:
        items: list[dict] = []
        if source in (None, "douyin"):
            records, _ = self.task_repository.list(limit=100)
            items.extend(
                {
                    "source": "douyin",
                    "kind": _KIND_LABELS["douyin"],
                    "id": item.id,
                    "title": item.title,
                    "status": item.status.value,
                    "message": item.message or (item.error or ""),
                    "created_at": item.created_at.isoformat(),
                    "updated_at": item.updated_at.isoformat(),
                    "retryable": item.status == TaskStatus.FAILED,
                }
                for item in records
            )
        if source in (None, "xhs"):
            items.extend(
                {
                    "source": "xhs",
                    "kind": _KIND_LABELS["xhs"],
                    "id": job.id,
                    "title": _job_title(job),
                    "status": job.status.value,
                    "message": job.message or (job.error or ""),
                    "created_at": job.created_at.isoformat(),
                    "updated_at": job.updated_at.isoformat(),
                    "retryable": False,
                }
                for job in self.xhs_jobs.list()
            )
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items

    def retry(self, source: str, item_id: str) -> dict:
        if source != "douyin":
            raise ValueError("该来源的任务暂不支持重试")
        task = self.pipeline.retry(item_id)
        if task is None:
            raise KeyError(f"任务不存在：{item_id}")
        return {"source": "douyin", "id": task.id, "status": task.status, "message": task.message}


def get_queue_service() -> QueueService:
    raise RuntimeError("Dependency override is not configured")


@router.get("")
def list_queue(
    source: str | None = None, service: QueueService = Depends(get_queue_service)
) -> dict:
    return {"items": service.list(source)}


@router.post("/{source}/{item_id}/retry")
def retry_queue_item(
    source: str, item_id: str, service: QueueService = Depends(get_queue_service)
) -> dict:
    try:
        return service.retry(source, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
