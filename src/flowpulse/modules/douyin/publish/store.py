"""抖音发布任务存储：fp_douyin_publish_tasks（PG）或 data/douyin/publish_tasks.json（文件）。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.db.models import DouyinPublishTaskRow

_DATETIME_FIELDS = ("scheduled_at", "published_at", "created_at", "updated_at")

FIELDS = (
    "id", "title", "desc", "topics", "media_paths", "media_type", "visibility",
    "allow_save", "status", "scheduled_at", "result_url", "error", "published_at",
    "created_at", "updated_at",
)

STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_PUBLISHING = "publishing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _from_iso(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class DouyinPublishStore:
    def __init__(self, sessionmaker_: sessionmaker[Session] | None, data_dir: Path):
        self._sessionmaker = sessionmaker_
        self._json_path = data_dir / "douyin" / "publish_tasks.json"
        self._json_path.parent.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = (
                    session.execute(
                        select(DouyinPublishTaskRow).order_by(DouyinPublishTaskRow.id.desc())
                    )
                    .scalars()
                    .all()
                )
                return [self._to_dict(r) for r in rows]
        data = read_json(self._json_path, {"tasks": [], "next_id": 1})
        return [dict(t) for t in data.get("tasks", [])]

    def get(self, task_id: int) -> dict | None:
        for row in self.list():
            if row["id"] == task_id:
                return row
        return None

    def create(self, fields: dict) -> dict:
        now = _now_iso()
        row = {k: fields.get(k, "" if k != "media_paths" else []) for k in FIELDS if k != "id"}
        row.update(
            {
                "media_paths": list(fields.get("media_paths") or []),
                "media_type": fields.get("media_type", "video"),
                "visibility": fields.get("visibility", "public"),
                "allow_save": bool(fields.get("allow_save", True)),
                "status": STATUS_DRAFT,
                "result_url": "",
                "error": "",
                "published_at": None,
                "scheduled_at": _to_iso(fields.get("scheduled_at")),
                "created_at": now,
                "updated_at": now,
            }
        )
        return self._insert(row)

    def update(self, task_id: int, updates: dict) -> dict | None:
        allowed = {k: v for k, v in updates.items() if k in FIELDS and k != "id"}
        allowed["updated_at"] = _now_iso()
        self._update(task_id, allowed)
        return self.get(task_id)

    def delete(self, task_id: int) -> bool:
        if self.get(task_id) is None:
            return False
        if self._sessionmaker is not None:
            from sqlalchemy import delete as sa_delete

            with self._sessionmaker() as session:
                session.execute(
                    sa_delete(DouyinPublishTaskRow).where(DouyinPublishTaskRow.id == task_id)
                )
                session.commit()
        else:
            data = read_json(self._json_path, {"tasks": [], "next_id": 1})
            data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
            atomic_write_json(self._json_path, data)
        return True

    def next_due(self, now_iso: str) -> dict | None:
        """最早的 pending（含定时到期）任务；publishing 的由执行方独占。"""
        due = [
            t
            for t in self.list()
            if t["status"] == STATUS_PENDING
            and (not t.get("scheduled_at") or str(t["scheduled_at"]) <= now_iso)
        ]
        return min(due, key=lambda t: t["id"]) if due else None

    # ---- 后端 ----

    def _insert(self, row: dict) -> dict:
        if self._sessionmaker is not None:
            values = {k: (_from_iso(v) if k in _DATETIME_FIELDS else v) for k, v in row.items()}
            with self._sessionmaker() as session:
                obj = DouyinPublishTaskRow(**values)
                session.add(obj)
                session.commit()
                session.refresh(obj)
                return self._to_dict(obj)
        data = read_json(self._json_path, {"tasks": [], "next_id": 1})
        row["id"] = data["next_id"]
        data["next_id"] += 1
        data["tasks"].insert(0, row)
        atomic_write_json(self._json_path, data)
        return row

    def _update(self, task_id: int, updates: dict) -> None:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                obj = session.get(DouyinPublishTaskRow, task_id)
                if obj is None:
                    return
                for key, value in updates.items():
                    if key in _DATETIME_FIELDS:
                        value = _from_iso(value)
                    setattr(obj, key, value)
                session.commit()
        else:
            data = read_json(self._json_path, {"tasks": [], "next_id": 1})
            for task in data["tasks"]:
                if task["id"] == task_id:
                    task.update(updates)
                    break
            atomic_write_json(self._json_path, data)

    @staticmethod
    def _to_dict(row: DouyinPublishTaskRow) -> dict:
        return {
            "id": row.id,
            "title": row.title,
            "desc": row.desc,
            "topics": row.topics,
            "media_paths": row.media_paths or [],
            "media_type": row.media_type,
            "visibility": row.visibility,
            "allow_save": row.allow_save,
            "status": row.status,
            "scheduled_at": _to_iso(row.scheduled_at),
            "result_url": row.result_url,
            "error": row.error,
            "published_at": _to_iso(row.published_at),
            "created_at": _to_iso(row.created_at),
            "updated_at": _to_iso(row.updated_at),
        }
