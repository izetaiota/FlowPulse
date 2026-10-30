"""通用链接下载（P2）：分享文案抽链 → yt-dlp 任务化下载 → 历史/文件管理。

yt-dlp 为可选依赖（`pip install -e ".[download]"`），未安装时 API 优雅报错；
下载在独立线程执行（阻塞式 YoutubeDL API），进度写回任务文件供前端轮询。
"""

from __future__ import annotations

import asyncio
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# 分享文案里的 URL 提取（排除常见中文标点与引号）
_URL_RE = re.compile(r"https?://[^\s，,。；;！!？?\"'<>【】\[\]（）()]+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def extract_urls(text: str) -> list[str]:
    """从粘贴的分享文案中抽取 URL（去重保序）。"""
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_RE.findall(text or ""):
        url = match.rstrip("\\")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def source_hint(url: str) -> str:
    """按域名粗判来源（决定前端是否给「提交转写」入口，目前仅抖音支持）。"""
    host = url.lower()
    if "douyin.com" in host:
        return "douyin"
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    if "xiaohongshu.com" in host:
        return "xhs"
    return "other"


def yt_dlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


class DownloadTask(BaseModel):
    id: str
    url: str
    source: str = "other"
    title: str = ""
    status: str = "pending"  # pending | running | completed | failed
    progress: int = 0  # 0~100
    message: str = ""
    error: str | None = None
    filename: str = ""
    file_size: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class DownloadStore:
    """每个任务一个目录 data/downloads/<id>/：task.json + 下载产物。"""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def task_dir(self, task_id: str) -> Path:
        return self.root / task_id

    def create(self, url: str) -> DownloadTask:
        task = DownloadTask(id=uuid.uuid4().hex, url=url, source=source_hint(url))
        self.save(task)
        return task

    def save(self, task: DownloadTask) -> None:
        task.updated_at = _now()
        self.task_dir(task.id).mkdir(parents=True, exist_ok=True)
        (self.task_dir(task.id) / "task.json").write_text(
            task.model_dump_json(), encoding="utf-8"
        )

    def get(self, task_id: str) -> DownloadTask | None:
        path = self.task_dir(task_id) / "task.json"
        if not path.is_file():
            return None
        try:
            return DownloadTask.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def list(self) -> list[DownloadTask]:
        tasks = [self.get(p.name) for p in self.root.iterdir() if p.is_dir()]
        return sorted((t for t in tasks if t), key=lambda t: t.created_at, reverse=True)

    def delete(self, task_id: str) -> bool:
        directory = self.task_dir(task_id)
        if not directory.is_dir():
            return False
        shutil.rmtree(directory, ignore_errors=True)
        return True


class DownloadService:
    def __init__(self, store: DownloadStore):
        self.store = store
        self._running: set[asyncio.Task] = set()

    # ---- 提交 ----

    def submit_text(self, text: str) -> list[DownloadTask]:
        if not yt_dlp_available():
            raise RuntimeError("未安装 yt-dlp（pip install -e \".[download]\"），无法下载")
        urls = extract_urls(text)
        if not urls:
            raise ValueError("未从文案中识别到链接")
        tasks = [self.store.create(url) for url in urls]
        for task in tasks:
            self._start(task.id)
        return tasks

    def retry(self, task_id: str) -> DownloadTask:
        task = self.store.get(task_id)
        if task is None:
            raise KeyError(f"任务不存在：{task_id}")
        if task.status == "running":
            return task
        task.status = "pending"
        task.progress = 0
        task.error = None
        task.message = "等待重试"
        self.store.save(task)
        self._start(task.id)
        return task

    def _start(self, task_id: str) -> None:
        task = asyncio.create_task(self._run(task_id))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    # ---- 执行 ----

    async def _run(self, task_id: str) -> None:
        await asyncio.to_thread(self._run_sync, task_id)

    def _run_sync(self, task_id: str) -> None:
        task = self.store.get(task_id)
        if task is None:
            return
        task.status = "running"
        task.message = "开始下载"
        task.error = None
        self.store.save(task)

        try:
            filename, size, title = _download_with_ytdlp(
                self.store.task_dir(task_id), task.url, self._progress_hook(task_id)
            )
        except Exception as exc:  # noqa: BLE001 - 失败写入任务，不抛给事件循环
            task = self.store.get(task_id) or task
            task.status = "failed"
            task.error = str(exc)[:500]
            task.message = "下载失败"
            self.store.save(task)
            return

        task = self.store.get(task_id) or task
        task.status = "completed"
        task.progress = 100
        task.filename = filename
        task.file_size = size
        task.title = title or task.title
        task.message = "完成"
        self.store.save(task)

    def _progress_hook(self, task_id: str):
        def hook(payload: dict) -> None:
            task = self.store.get(task_id)
            if task is None or task.status != "running":
                return
            if payload.get("status") == "downloading":
                total = payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
                done = payload.get("downloaded_bytes") or 0
                task.progress = int(done * 100 / total) if total else task.progress
                task.message = "下载中"
                self.store.save(task)
            elif payload.get("status") == "finished":
                task.progress = 99
                task.message = "下载完成，处理中"
                self.store.save(task)

        return hook


def _download_with_ytdlp(
    workdir: Path, url: str, progress_hook
) -> tuple[str, int, str]:
    """同步执行 yt-dlp，返回 (产物文件名, 字节数, 标题)。"""
    import yt_dlp

    from flowpulse.modules.douyin.services.media import find_ffmpeg

    options: dict[str, Any] = {
        "outtmpl": str(workdir / "%(title).80s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": False,
        "progress_hooks": [progress_hook],
    }
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        options["ffmpeg_location"] = ffmpeg
        options["format"] = "bv*+ba/b"
    else:
        options["format"] = "b"  # 无 ffmpeg 时只下最佳单格式（不合并）
    workdir.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        title = (info or {}).get("title") or ""
    # 找目录里最大的媒体文件作为产物
    candidates = [
        p
        for p in workdir.iterdir()
        if p.is_file() and p.suffix.lower() in {".mp4", ".mp3", ".m4a", ".webm", ".mkv", ".flv", ".mov", ".opus", ".ogg", ".wav", ".part"}
    ]
    if not candidates:
        raise RuntimeError("下载完成但未找到产物文件")
    media = max(candidates, key=lambda p: p.stat().st_size)
    if media.suffix.lower() == ".part":
        raise RuntimeError("下载未完成（产物仍是 .part）")
    return media.name, media.stat().st_size, title
