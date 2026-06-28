from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from douyin_transcribe.models import (
    Artifact,
    Capabilities,
    TaskPage,
    TaskRecord,
    TaskResult,
    TaskStatus,
    TranscribeRequest,
)
from douyin_transcribe.services.media import ffmpeg_available
from douyin_transcribe.services.pipeline import PipelineService
from douyin_transcribe.storage.tasks import TaskRepository

router = APIRouter()


def get_pipeline() -> PipelineService:
    raise RuntimeError("Dependency override is not configured")


def get_repository() -> TaskRepository:
    raise RuntimeError("Dependency override is not configured")


@router.post("/api/v1/tasks/transcribe", response_model=TaskRecord, status_code=202)
async def create_transcribe_task(
    request: TranscribeRequest, pipeline: PipelineService = Depends(get_pipeline)
) -> TaskRecord:
    return pipeline.create(request)


@router.get("/api/v1/capabilities", response_model=Capabilities)
async def capabilities(pipeline: PipelineService = Depends(get_pipeline)) -> Capabilities:
    engines = {
        name: await engine.probe() for name, engine in pipeline.transcriber.transcribers.items()
    }
    return Capabilities(
        service_version="0.2.0",
        engines=engines,
        formats=["json", "srt", "markdown"],
        exporters=["download"],
        limits={"max_download_bytes": pipeline.max_download_bytes},
    )


@router.get("/api/v1/tasks", response_model=TaskPage)
async def list_tasks(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    repository: TaskRepository = Depends(get_repository),
) -> TaskPage:
    try:
        items, next_cursor = repository.list(limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return TaskPage(
        items=[repository.list_item(item) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/api/v1/tasks/{task_id}", response_model=TaskRecord)
async def get_task(
    task_id: str, repository: TaskRepository = Depends(get_repository)
) -> TaskRecord:
    task = repository.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.get("/api/v1/tasks/{task_id}/result", response_model=TaskResult)
async def get_task_result(
    task_id: str, repository: TaskRepository = Depends(get_repository)
) -> TaskResult:
    task = repository.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(409, "Task is not completed")
    result = repository.result(task_id)
    if not result:
        raise HTTPException(404, "Task result not found")
    return result


@router.post("/api/v1/tasks/{task_id}/retry", response_model=TaskRecord, status_code=202)
async def retry_task(task_id: str, pipeline: PipelineService = Depends(get_pipeline)) -> TaskRecord:
    task = pipeline.retry(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.get("/api/v1/tasks/{task_id}/artifacts", response_model=list[Artifact])
async def list_artifacts(
    task_id: str, repository: TaskRepository = Depends(get_repository)
) -> list[Artifact]:
    task = repository.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.artifacts


@router.get("/api/v1/tasks/{task_id}/artifacts/{name}")
async def download_artifact(
    task_id: str,
    name: str,
    repository: TaskRepository = Depends(get_repository),
):
    path = repository.artifact_path(task_id, name)
    if not path:
        raise HTTPException(404, "Artifact not found")
    task = repository.get(task_id)
    artifact = next(item for item in task.artifacts if item.name == name)
    return FileResponse(path, media_type=artifact.media_type, filename=name)


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    engines = {
        name: await engine.probe() for name, engine in pipeline.transcriber.transcribers.items()
    }
    has_ffmpeg = ffmpeg_available()
    return {
        "status": "ready" if has_ffmpeg and any(engines.values()) else "degraded",
        "ffmpeg": has_ffmpeg,
        "transcribers": engines,
    }
