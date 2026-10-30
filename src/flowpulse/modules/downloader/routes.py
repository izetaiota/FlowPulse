"""下载与素材库 API：/api/v1/downloads（任务 CRUD）+ /api/v1/downloads/files（媒体浏览）。

媒体库按「根」浏览：downloads = data/downloads（本模块产物）、xhs = data/xhs/jobs（小红书任务产物）。
所有文件访问均做目录穿越防护（resolve 后必须落在根内）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from flowpulse.modules.downloader.service import DownloadService

router = APIRouter(prefix="/api/v1/downloads", tags=["downloads"])

# 媒体库根目录（root id → data 子目录）；新增来源时在此登记
MEDIA_ROOTS: dict[str, str] = {
    "downloads": "downloads",
    "xhs": "xhs/jobs",
}

PREVIEW_SUFFIXES = {
    ".mp4", ".webm", ".mov", ".mkv", ".flv",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".mp3", ".m4a", ".wav", ".ogg", ".opus",
}


def get_download_service() -> DownloadService:
    raise RuntimeError("Dependency override is not configured")


class DownloadSubmitRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


@router.post("", status_code=202)
async def submit(
    request: DownloadSubmitRequest, service: DownloadService = Depends(get_download_service)
) -> dict:
    # async 处理器：submit_text 内部要 create_task 拉起后台下载（事件循环内）
    try:
        tasks = service.submit_text(request.text)
    except RuntimeError as exc:  # 依赖缺失
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:  # 无链接
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tasks": [t.model_dump() for t in tasks]}


@router.get("")
def list_tasks(service: DownloadService = Depends(get_download_service)) -> dict:
    return {"tasks": [t.model_dump() for t in service.store.list()]}


@router.get("/{task_id}")
def get_task(task_id: str, service: DownloadService = Depends(get_download_service)) -> dict:
    task = service.store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.model_dump()


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str, service: DownloadService = Depends(get_download_service)
) -> dict:
    try:
        return service.retry(task_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{task_id}")
def delete_task(
    task_id: str, service: DownloadService = Depends(get_download_service)
) -> dict:
    if not service.store.delete(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"deleted": True}


# ---- 媒体库浏览（素材库） ----


def _resolve_media(root_id: str, rel_path: str, service: DownloadService) -> Path:
    sub = MEDIA_ROOTS.get(root_id)
    if sub is None:
        raise HTTPException(status_code=400, detail=f"未知媒体根：{root_id}")
    base = (service.store.root.parent / sub).resolve()
    target = (base / rel_path).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(status_code=400, detail="非法路径")
    return target


@router.get("/files/list")
def list_files(
    root: str = "downloads",
    path: str = "",
    service: DownloadService = Depends(get_download_service),
) -> dict:
    base = _resolve_media(root, "", service)
    directory = _resolve_media(root, path, service)
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="目录不存在")
    entries = []
    for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name == "task.json" or item.name.startswith("."):
            continue
        stat = item.stat()
        entries.append(
            {
                "name": item.name,
                "is_dir": item.is_dir(),
                "size": 0 if item.is_dir() else stat.st_size,
                "mtime": int(stat.st_mtime),
                "previewable": item.is_file() and item.suffix.lower() in PREVIEW_SUFFIXES,
                "path": (f"{path}/{item.name}" if path else item.name),
            }
        )
    return {"root": root, "path": path, "entries": entries}


@router.get("/files/content")
def file_content(
    root: str,
    path: str,
    service: DownloadService = Depends(get_download_service),
) -> FileResponse:
    target = _resolve_media(root, path, service)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, filename=target.name)


@router.delete("/files/content")
def delete_file(
    root: str,
    path: str,
    service: DownloadService = Depends(get_download_service),
) -> dict:
    target = _resolve_media(root, path, service)
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    else:
        target.unlink()
    return {"deleted": True}
