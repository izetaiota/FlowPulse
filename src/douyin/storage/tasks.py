import re
from pathlib import Path
from uuid import UUID

from douyin.models import (
    TaskListItem,
    TaskRecord,
    TaskResult,
    Transcript,
    VideoInfo,
    utc_now,
)


class TaskRepository:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "tasks"
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, task: TaskRecord) -> TaskRecord:
        task.updated_at = utc_now()
        directory = task.task_dir(self.root.parent)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "task.json"
        temporary = directory / "task.json.tmp"
        temporary.write_text(task.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return task

    def get(self, task_id: str) -> TaskRecord | None:
        directory = self._task_dir(task_id)
        if not directory:
            return None
        path = directory / "task.json"
        if not path.is_file():
            return None
        return TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, limit: int = 20, cursor: str | None = None) -> tuple[list[TaskRecord], str | None]:
        tasks = []
        for path in self.root.glob("*/task.json"):
            try:
                tasks.append(TaskRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        tasks.sort(key=lambda item: (item.created_at, item.id), reverse=True)

        start = 0
        if cursor:
            positions = [index for index, item in enumerate(tasks) if item.id == cursor]
            if not positions:
                raise ValueError("Invalid task cursor")
            start = positions[0] + 1

        page = tasks[start : start + limit]
        has_more = start + limit < len(tasks)
        next_cursor = page[-1].id if page and has_more else None
        return page, next_cursor

    def find_by_client_request_id(self, client_request_id: str) -> TaskRecord | None:
        tasks, cursor = self.list(limit=100)
        while True:
            for task in tasks:
                if task.request.client_request_id == client_request_id:
                    return task
            if not cursor:
                return None
            tasks, cursor = self.list(limit=100, cursor=cursor)

    def list_item(self, task: TaskRecord) -> TaskListItem:
        source = self._read_source(task.id)
        if source:
            title = " ".join(source.title.split())
            author = source.author
            source_url = source.source_url
            cover_url = source.cover_url
        else:
            title = fallback_title(task.request.input)
            author = None
            source_url = None
            cover_url = None
        return TaskListItem(
            id=task.id,
            input=task.request.input,
            title=title,
            author=author,
            source_url=source_url,
            cover_url=cover_url,
            status=task.status,
            progress=task.progress,
            message=task.message,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    def result(self, task_id: str) -> TaskResult | None:
        task = self.get(task_id)
        directory = self._task_dir(task_id)
        if not task or not directory:
            return None
        source_path = directory / "source.json"
        transcript_path = directory / "transcript.json"
        if not source_path.is_file() or not transcript_path.is_file():
            return None
        return TaskResult(
            task_id=task.id,
            source=VideoInfo.model_validate_json(source_path.read_text(encoding="utf-8")),
            transcript=Transcript.model_validate_json(
                transcript_path.read_text(encoding="utf-8")
            ),
            artifacts=task.artifacts,
        )

    def _read_source(self, task_id: str) -> VideoInfo | None:
        directory = self._task_dir(task_id)
        if not directory:
            return None
        path = directory / "source.json"
        if not path.is_file():
            return None
        try:
            return VideoInfo.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def artifact_path(self, task_id: str, name: str) -> Path | None:
        task = self.get(task_id)
        if not task or name not in {item.name for item in task.artifacts}:
            return None
        directory = self._task_dir(task_id)
        if not directory:
            return None
        path = directory / name
        return path if path.is_file() else None

    def _task_dir(self, task_id: str) -> Path | None:
        try:
            normalized = str(UUID(task_id))
        except ValueError:
            return None
        return self.root / normalized


def fallback_title(input_text: str) -> str:
    match = re.search(r"https?://[^\s]+", input_text)
    if match:
        return f"抖音任务 · {match.group(0).rstrip('.,，。!！')}"
    normalized = " ".join(input_text.split())
    if normalized and normalized.count("?") / len(normalized) < 0.3:
        return normalized
    return "未命名抖音任务"
