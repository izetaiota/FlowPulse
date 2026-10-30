"""抖音作品监控存储：fp_ks_monitors / fp_ks_contents（PG）或 data/ks/monitor*.json。

结构与 xhs 监控仓储一致（同套双模式约定），内容字段按抖音 aweme 语义命名。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.db.models import KsContentRow, KsMonitorRow

_DATETIME_FIELDS = ("last_scan_at", "first_seen_at", "created_at", "updated_at")

MONITOR_FIELDS = (
    "id", "kind", "target", "name", "interval_minutes", "include_keywords",
    "exclude_keywords", "backfill_count", "status", "last_scan_at",
    "last_scan_status", "last_error", "created_at", "updated_at",
)

CONTENT_FIELDS = (
    "id", "monitor_id", "photo_id", "title", "author", "author_id", "url", "cover",
    "media_type", "liked_count", "create_time", "extra", "notified",
    "first_seen_at", "updated_at",
)


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


class KsMonitorRepository:
    def __init__(self, sessionmaker_: sessionmaker[Session] | None, data_dir: Path):
        self._sessionmaker = sessionmaker_
        self._monitors_path = data_dir / "ks" / "monitors.json"
        self._contents_path = data_dir / "ks" / "monitor_contents.json"
        self._monitors_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- 监控目标 ----

    def list_monitors(self, status: str | None = None) -> list[dict]:
        rows = self._load_monitors()
        if status:
            rows = [r for r in rows if r["status"] == status]
        return rows

    def get_monitor(self, monitor_id: int) -> dict | None:
        for row in self._load_monitors():
            if row["id"] == monitor_id:
                return row
        return None

    def create_monitor(self, fields: dict) -> dict:
        now = _now_iso()
        row = {k: fields.get(k, "") for k in MONITOR_FIELDS if k != "id"}
        row.update(
            {
                "kind": fields.get("kind", "keyword"),
                "interval_minutes": int(fields.get("interval_minutes", 30)),
                "backfill_count": int(fields.get("backfill_count", 10)),
                "include_keywords": fields.get("include_keywords", ""),
                "exclude_keywords": fields.get("exclude_keywords", ""),
                "status": fields.get("status", "active"),
                "last_scan_at": None,
                "last_scan_status": "never",
                "last_error": "",
                "created_at": now,
                "updated_at": now,
            }
        )
        return self._insert_monitor(row)

    def update_monitor(self, monitor_id: int, updates: dict) -> dict | None:
        allowed = {k: v for k, v in updates.items() if k in MONITOR_FIELDS and k != "id"}
        allowed["updated_at"] = _now_iso()
        self._update_monitor(monitor_id, allowed)
        return self.get_monitor(monitor_id)

    def delete_monitor(self, monitor_id: int) -> bool:
        if self.get_monitor(monitor_id) is None:
            return False
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                session.execute(
                    sa_delete(KsContentRow).where(KsContentRow.monitor_id == monitor_id)
                )
                session.execute(sa_delete(KsMonitorRow).where(KsMonitorRow.id == monitor_id))
                session.commit()
        else:
            data = read_json(self._monitors_path, {"monitors": [], "next_id": 1})
            data["monitors"] = [m for m in data["monitors"] if m["id"] != monitor_id]
            atomic_write_json(self._monitors_path, data)
            contents = read_json(self._contents_path, {"contents": [], "next_id": 1})
            contents["contents"] = [
                c for c in contents["contents"] if c["monitor_id"] != monitor_id
            ]
            atomic_write_json(self._contents_path, contents)
        return True

    # ---- 作品记录 ----

    def aweme_exists(self, photo_id: str) -> bool:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                return session.scalar(
                    select(func.count()).where(KsContentRow.photo_id == photo_id)
                ) > 0
        contents = read_json(self._contents_path, {"contents": [], "next_id": 1})
        return any(c["photo_id"] == photo_id for c in contents["contents"])

    def add_content(self, fields: dict) -> dict:
        now = _now_iso()
        row = {k: fields.get(k, "") for k in CONTENT_FIELDS if k != "id"}
        row.update(
            {
                "monitor_id": fields.get("monitor_id"),
                "photo_id": fields["photo_id"],
                "create_time": int(fields.get("create_time") or 0),
                "notified": bool(fields.get("notified", False)),
                "first_seen_at": fields.get("first_seen_at") or now,
                "updated_at": now,
                "extra": fields.get("extra") or {},
            }
        )
        return self._insert_content(row)

    def list_contents(
        self, monitor_id: int | None = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict], int]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                query = select(KsContentRow)
                count_query = select(func.count()).select_from(KsContentRow)
                if monitor_id is not None:
                    query = query.where(KsContentRow.monitor_id == monitor_id)
                    count_query = count_query.where(KsContentRow.monitor_id == monitor_id)
                total = session.scalar(count_query) or 0
                rows = (
                    session.execute(
                        query.order_by(
                            KsContentRow.first_seen_at.desc(), KsContentRow.id.desc()
                        )
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                    .scalars()
                    .all()
                )
                return [self._content_to_dict(r) for r in rows], total
        contents = read_json(self._contents_path, {"contents": [], "next_id": 1}).get("contents", [])
        if monitor_id is not None:
            contents = [c for c in contents if c["monitor_id"] == monitor_id]
        contents = sorted(
            contents, key=lambda c: (c.get("first_seen_at") or "", c["id"]), reverse=True
        )
        total = len(contents)
        start = (page - 1) * page_size
        return contents[start : start + page_size], total

    def mark_notified(self, content_ids: list[int]) -> None:
        if not content_ids:
            return
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                for row in session.execute(
                    select(KsContentRow).where(KsContentRow.id.in_(content_ids))
                ).scalars():
                    row.notified = True
                session.commit()
        else:
            contents = read_json(self._contents_path, {"contents": [], "next_id": 1})
            for content in contents["contents"]:
                if content["id"] in content_ids:
                    content["notified"] = True
            atomic_write_json(self._contents_path, contents)

    def content_stats(self) -> dict[int, int]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = session.execute(
                    select(KsContentRow.monitor_id, func.count())
                    .where(KsContentRow.monitor_id.isnot(None))
                    .group_by(KsContentRow.monitor_id)
                ).all()
                return {int(mid): int(count) for mid, count in rows}
        contents = read_json(self._contents_path, {"contents": [], "next_id": 1}).get("contents", [])
        stats: dict[int, int] = {}
        for content in contents:
            if content.get("monitor_id") is not None:
                stats[int(content["monitor_id"])] = stats.get(int(content["monitor_id"]), 0) + 1
        return stats

    # ---- 后端实现 ----

    def _load_monitors(self) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = (
                    session.execute(select(KsMonitorRow).order_by(KsMonitorRow.id))
                    .scalars()
                    .all()
                )
                return [self._monitor_to_dict(r) for r in rows]
        data = read_json(self._monitors_path, {"monitors": [], "next_id": 1})
        return [dict(m) for m in data.get("monitors", [])]

    def _insert_monitor(self, row: dict) -> dict:
        if self._sessionmaker is not None:
            values = {k: (_from_iso(v) if k in _DATETIME_FIELDS else v) for k, v in row.items()}
            with self._sessionmaker() as session:
                obj = KsMonitorRow(**values)
                session.add(obj)
                session.commit()
                session.refresh(obj)
                return self._monitor_to_dict(obj)
        data = read_json(self._monitors_path, {"monitors": [], "next_id": 1})
        row["id"] = data["next_id"]
        data["next_id"] += 1
        data["monitors"].append(row)
        atomic_write_json(self._monitors_path, data)
        return row

    def _update_monitor(self, monitor_id: int, updates: dict) -> None:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                obj = session.get(KsMonitorRow, monitor_id)
                if obj is None:
                    return
                for key, value in updates.items():
                    if key in _DATETIME_FIELDS:
                        value = _from_iso(value)
                    setattr(obj, key, value)
                session.commit()
        else:
            data = read_json(self._monitors_path, {"monitors": [], "next_id": 1})
            for monitor in data["monitors"]:
                if monitor["id"] == monitor_id:
                    monitor.update(updates)
                    break
            atomic_write_json(self._monitors_path, data)

    def _insert_content(self, row: dict) -> dict:
        if self._sessionmaker is not None:
            values = {k: (_from_iso(v) if k in _DATETIME_FIELDS else v) for k, v in row.items()}
            with self._sessionmaker() as session:
                obj = KsContentRow(**values)
                session.add(obj)
                session.commit()
                session.refresh(obj)
                return self._content_to_dict(obj)
        data = read_json(self._contents_path, {"contents": [], "next_id": 1})
        row["id"] = data["next_id"]
        data["next_id"] += 1
        data["contents"].append(row)
        atomic_write_json(self._contents_path, data)
        return row

    @staticmethod
    def _monitor_to_dict(row: KsMonitorRow) -> dict:
        return {
            "id": row.id,
            "kind": row.kind,
            "target": row.target,
            "name": row.name,
            "interval_minutes": row.interval_minutes,
            "include_keywords": row.include_keywords,
            "exclude_keywords": row.exclude_keywords,
            "backfill_count": row.backfill_count,
            "status": row.status,
            "last_scan_at": _to_iso(row.last_scan_at),
            "last_scan_status": row.last_scan_status,
            "last_error": row.last_error,
            "created_at": _to_iso(row.created_at),
            "updated_at": _to_iso(row.updated_at),
        }

    @staticmethod
    def _content_to_dict(row: KsContentRow) -> dict:
        return {
            "id": row.id,
            "monitor_id": row.monitor_id,
            "photo_id": row.photo_id,
            "title": row.title,
            "author": row.author,
            "author_id": row.author_id,
            "url": row.url,
            "cover": row.cover,
            "media_type": row.media_type,
            "liked_count": row.liked_count,
            "create_time": row.create_time,
            "extra": row.extra or {},
            "notified": row.notified,
            "first_seen_at": _to_iso(row.first_seen_at),
            "updated_at": _to_iso(row.updated_at),
        }
