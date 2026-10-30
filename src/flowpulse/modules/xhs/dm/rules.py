"""小红书私信规则与审核草稿存储（T4.2）：fp_xhs_dm_rules / fp_xhs_dm_drafts（PG）或 JSON 文件。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.db.models import XhsDmDraftRow, XhsDmRuleRow

_DATETIME_FIELDS = ("created_at", "updated_at", "sent_at")

RULE_FIELDS = ("id", "name", "keywords", "reply_template", "enabled", "created_at", "updated_at")
DRAFT_FIELDS = (
    "id", "conv_id", "peer_uid", "peer_nickname", "last_text", "rule_id",
    "rule_name", "suggested_reply", "status", "error", "sent_at", "created_at", "updated_at",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _from_iso(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _to_iso(value):
    if value in (None, ""):
        return None
    return value.isoformat(timespec="seconds") if isinstance(value, datetime) else str(value)


class DmRuleStore:
    def __init__(self, sessionmaker_: sessionmaker[Session] | None, data_dir: Path):
        self._sessionmaker = sessionmaker_
        self._rules_path = data_dir / "xhs" / "dm_rules.json"
        self._drafts_path = data_dir / "xhs" / "dm_drafts.json"
        self._rules_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- 规则 ----

    def list_rules(self) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = session.execute(select(XhsDmRuleRow).order_by(XhsDmRuleRow.id)).scalars().all()
                return [
                    {
                        "id": r.id, "name": r.name, "keywords": r.keywords,
                        "reply_template": r.reply_template, "enabled": r.enabled,
                        "created_at": _to_iso(r.created_at), "updated_at": _to_iso(r.updated_at),
                    }
                    for r in rows
                ]
        data = read_json(self._rules_path, {"rules": [], "next_id": 1})
        return [dict(r) for r in data.get("rules", [])]

    def create_rule(self, fields: dict) -> dict:
        now = _now_iso()
        row = {
            "name": fields.get("name", ""),
            "keywords": fields.get("keywords", ""),
            "reply_template": fields.get("reply_template", ""),
            "enabled": bool(fields.get("enabled", True)),
            "created_at": now,
            "updated_at": now,
        }
        return self._insert(XhsDmRuleRow, self._rules_path, "rules", row)

    def update_rule(self, rule_id: int, updates: dict) -> dict | None:
        allowed = {k: v for k, v in updates.items() if k in RULE_FIELDS and k != "id"}
        allowed["updated_at"] = _now_iso()
        self._update(XhsDmRuleRow, self._rules_path, "rules", rule_id, allowed)
        for rule in self.list_rules():
            if rule["id"] == rule_id:
                return rule
        return None

    def delete_rule(self, rule_id: int) -> bool:
        return self._delete(XhsDmRuleRow, self._rules_path, "rules", rule_id)

    # ---- 草稿 ----

    def list_drafts(self, status: str | None = None) -> list[dict]:
        drafts = self._load_drafts()
        if status:
            drafts = [d for d in drafts if d["status"] == status]
        return drafts

    def create_draft(self, fields: dict) -> dict:
        now = _now_iso()
        row = {
            "conv_id": fields["conv_id"],
            "peer_uid": fields.get("peer_uid", ""),
            "peer_nickname": fields.get("peer_nickname", ""),
            "last_text": fields.get("last_text", ""),
            "rule_id": fields.get("rule_id"),
            "rule_name": fields.get("rule_name", ""),
            "suggested_reply": fields.get("suggested_reply", ""),
            "status": "pending",
            "error": "",
            "sent_at": None,
            "created_at": now,
            "updated_at": now,
        }
        return self._insert(XhsDmDraftRow, self._drafts_path, "drafts", row)

    def draft_exists(self, conv_id: str, last_text: str) -> bool:
        return any(
            d["conv_id"] == conv_id and d["last_text"] == last_text and d["status"] == "pending"
            for d in self._load_drafts()
        )

    def review_draft(self, draft_id: int, decision: str) -> dict | None:
        if decision not in ("approved", "rejected"):
            raise ValueError("decision 必须是 approved / rejected")
        updated = self._update(
            XhsDmDraftRow, self._drafts_path, "drafts", draft_id,
            {"status": decision, "updated_at": _now_iso()},
        )
        for draft in self._load_drafts():
            if draft["id"] == draft_id:
                return draft
        return None

    def delete_draft(self, draft_id: int) -> bool:
        return self._delete(XhsDmDraftRow, self._drafts_path, "drafts", draft_id)

    def mark_sent(self, draft_id: int, ok: bool, error: str = "") -> dict | None:
        """记录发送结果：成功 → sent + sent_at；失败保持 approved 可重试（error 记录原因）。"""
        from datetime import datetime, timezone as tz

        updates = {"error": (error or "")[:500], "updated_at": _now_iso()}
        if ok:
            updates["status"] = "sent"
            updates["sent_at"] = datetime.now(tz.utc).isoformat(timespec="seconds")
        self._update(XhsDmDraftRow, self._drafts_path, "drafts", draft_id, updates)
        for draft in self._load_drafts():
            if draft["id"] == draft_id:
                return draft
        return None

    def _load_drafts(self) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = (
                    session.execute(select(XhsDmDraftRow).order_by(XhsDmDraftRow.id.desc()))
                    .scalars()
                    .all()
                )
                return [
                    {
                        "id": r.id, "conv_id": r.conv_id, "peer_uid": r.peer_uid,
                        "peer_nickname": r.peer_nickname, "last_text": r.last_text,
                        "rule_id": r.rule_id, "rule_name": r.rule_name,
                        "suggested_reply": r.suggested_reply, "status": r.status,
                        "error": r.error, "sent_at": _to_iso(r.sent_at),
                        "created_at": _to_iso(r.created_at), "updated_at": _to_iso(r.updated_at),
                    }
                    for r in rows
                ]
        data = read_json(self._drafts_path, {"drafts": [], "next_id": 1})
        return [dict(d) for d in data.get("drafts", [])]

    # ---- 通用双模式实现 ----

    def _insert(self, row_class, json_path: Path, collection: str, row: dict) -> dict:
        if self._sessionmaker is not None:
            values = {
                k: (_from_iso(v) if k in _DATETIME_FIELDS else v) for k, v in row.items()
            }
            with self._sessionmaker() as session:
                obj = row_class(**values)
                session.add(obj)
                session.commit()
                session.refresh(obj)
                return {"id": obj.id, **{k: v for k, v in row.items() if k != "id"}}
        data = read_json(json_path, {collection: [], "next_id": 1})
        row["id"] = data["next_id"]
        data["next_id"] += 1
        data[collection].insert(0, row)
        atomic_write_json(json_path, data)
        return row

    def _update(self, row_class, json_path: Path, collection: str, item_id: int, updates: dict) -> bool:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                obj = session.get(row_class, item_id)
                if obj is None:
                    return False
                for key, value in updates.items():
                    if key in _DATETIME_FIELDS:
                        value = _from_iso(value)
                    setattr(obj, key, value)
                session.commit()
            return True
        data = read_json(json_path, {collection: [], "next_id": 1})
        for item in data[collection]:
            if item["id"] == item_id:
                item.update(updates)
                atomic_write_json(json_path, data)
                return True
        return False

    def _delete(self, row_class, json_path: Path, collection: str, item_id: int) -> bool:
        if self._sessionmaker is not None:
            from sqlalchemy import delete as sa_delete

            with self._sessionmaker() as session:
                result = session.execute(sa_delete(row_class).where(row_class.id == item_id))
                session.commit()
                return bool(result.rowcount)
        data = read_json(json_path, {collection: [], "next_id": 1})
        before = len(data[collection])
        data[collection] = [i for i in data[collection] if i["id"] != item_id]
        if len(data[collection]) == before:
            return False
        atomic_write_json(json_path, data)
        return True
