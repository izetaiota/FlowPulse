from pathlib import Path
from uuid import UUID

from douyin_transcribe.models import TaskRecord, utc_now


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
