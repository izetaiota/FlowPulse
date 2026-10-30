"""统一账号中心存储：DATABASE_URL 模式走 fp_accounts 表，否则 data/accounts/accounts.json。

两种模式返回一致的 dict 结构（datetime 一律转 ISO 字符串），上层服务不感知后端。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.db.models import AccountRow

_DATETIME_FIELDS = ("last_check_at", "write_paused_until", "created_at", "updated_at")

# 行内允许出现的字段白名单（防止调用方误写未知键）
_FIELDS = (
    "id",
    "platform",
    "account_key",
    "kind",
    "name",
    "status",
    "last_check_at",
    "last_check_ok",
    "last_check_message",
    "extra",
    "credential_encrypted",
    "storage_state",
    "write_paused_until",
    "risk_level",
    "created_at",
    "updated_at",
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
    """ISO 字符串 → datetime（ORM DateTime 列只接受 datetime 对象）。"""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class AccountRepository:
    def __init__(self, sessionmaker_: sessionmaker[Session] | None, json_path: Path):
        self._sessionmaker = sessionmaker_
        self._json_path = json_path
        self._json_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- 读取 ----

    def list_accounts(self, platform: str | None = None) -> list[dict]:
        rows = self._load()
        if platform:
            rows = [r for r in rows if r["platform"] == platform]
        return rows

    def get(self, account_id: int) -> dict | None:
        for row in self._load():
            if row["id"] == account_id:
                return row
        return None

    def find_by_key(self, platform: str, account_key: str) -> dict | None:
        for row in self._load():
            if row["platform"] == platform and row["account_key"] == account_key:
                return row
        return None

    # ---- 写入 ----

    def upsert_builtin(
        self, platform: str, account_key: str, snapshot: dict
    ) -> dict:
        """模块提供方同步入口：只更新元数据/体检字段，不触碰凭证列。"""
        now = _now_iso()
        existing = self.find_by_key(platform, account_key)
        if existing is None:
            row = {
                "platform": platform,
                "account_key": account_key,
                "kind": "builtin",
                "name": snapshot.get("name", ""),
                "status": snapshot.get("status", "unknown"),
                "last_check_at": snapshot.get("last_check_at"),
                "last_check_ok": snapshot.get("last_check_ok"),
                "last_check_message": snapshot.get("last_check_message", ""),
                "extra": snapshot.get("extra") or {},
                "credential_encrypted": None,
                "storage_state": None,
                "write_paused_until": None,
                "risk_level": 0,
                "created_at": now,
                "updated_at": now,
            }
            return self._insert(row)
        updates = {
            "name": snapshot.get("name") or existing["name"],
            "status": snapshot.get("status", existing["status"]),
            "last_check_at": snapshot.get("last_check_at", existing["last_check_at"]),
            "last_check_ok": snapshot.get("last_check_ok", existing["last_check_ok"]),
            "last_check_message": snapshot.get(
                "last_check_message", existing["last_check_message"]
            ),
            "extra": {**(existing.get("extra") or {}), **(snapshot.get("extra") or {})},
            "updated_at": now,
        }
        self._update(existing["id"], updates)
        return self.get(existing["id"])

    def create_managed(
        self,
        platform: str,
        account_key: str,
        name: str,
        credential_encrypted: str | None = None,
        storage_state: dict | None = None,
    ) -> dict:
        if self.find_by_key(platform, account_key) is not None:
            raise ValueError(f"账号已存在：{platform}/{account_key}")
        now = _now_iso()
        row = {
            "platform": platform,
            "account_key": account_key,
            "kind": "managed",
            "name": name,
            "status": "unknown",
            "last_check_at": None,
            "last_check_ok": None,
            "last_check_message": "",
            "extra": {},
            "credential_encrypted": credential_encrypted,
            "storage_state": storage_state,
            "write_paused_until": None,
            "risk_level": 0,
            "created_at": now,
            "updated_at": now,
        }
        return self._insert(row)

    def update(self, account_id: int, updates: dict) -> dict | None:
        allowed = {k: v for k, v in updates.items() if k in _FIELDS and k != "id"}
        allowed["updated_at"] = _now_iso()
        self._update(account_id, allowed)
        return self.get(account_id)

    def delete(self, account_id: int) -> bool:
        if self.get(account_id) is None:
            return False
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                session.execute(sa_delete(AccountRow).where(AccountRow.id == account_id))
                session.commit()
        else:
            data = read_json(self._json_path, {"accounts": [], "next_id": 1})
            data["accounts"] = [a for a in data["accounts"] if a["id"] != account_id]
            atomic_write_json(self._json_path, data)
        return True

    # ---- 后端实现 ----

    def _load(self) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = session.execute(
                    select(AccountRow).order_by(AccountRow.platform, AccountRow.account_key)
                ).scalars().all()
                return [self._row_to_dict(row) for row in rows]
        data = read_json(self._json_path, {"accounts": [], "next_id": 1})
        return [dict(a) for a in data.get("accounts", [])]

    def _insert(self, row: dict) -> dict:
        if self._sessionmaker is not None:
            orm_values = {
                k: (_from_iso(v) if k in _DATETIME_FIELDS else v)
                for k, v in row.items()
                if k in _FIELDS
            }
            with self._sessionmaker() as session:
                obj = AccountRow(**orm_values)
                session.add(obj)
                session.commit()
                session.refresh(obj)
                return self._row_to_dict(obj)
        data = read_json(self._json_path, {"accounts": [], "next_id": 1})
        data["next_id"] = max(int(data.get("next_id", 1)), 1)
        row = dict(row)
        row["id"] = data["next_id"]
        data["next_id"] += 1
        data["accounts"].append(row)
        atomic_write_json(self._json_path, data)
        return row

    def _update(self, account_id: int, updates: dict) -> None:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                obj = session.get(AccountRow, account_id)
                if obj is None:
                    return
                for key, value in updates.items():
                    if key == "id":
                        continue
                    if key in _DATETIME_FIELDS:
                        value = _from_iso(value)
                    setattr(obj, key, value)
                session.commit()
        else:
            data = read_json(self._json_path, {"accounts": [], "next_id": 1})
            for account in data["accounts"]:
                if account["id"] == account_id:
                    account.update(updates)
                    break
            atomic_write_json(self._json_path, data)

    @staticmethod
    def _row_to_dict(row: AccountRow) -> dict:
        return {
            "id": row.id,
            "platform": row.platform,
            "account_key": row.account_key,
            "kind": row.kind,
            "name": row.name,
            "status": row.status,
            "last_check_at": _to_iso(row.last_check_at),
            "last_check_ok": row.last_check_ok,
            "last_check_message": row.last_check_message,
            "extra": row.extra or {},
            "credential_encrypted": row.credential_encrypted,
            "storage_state": row.storage_state,
            "write_paused_until": _to_iso(row.write_paused_until),
            "risk_level": row.risk_level,
            "created_at": _to_iso(row.created_at),
            "updated_at": _to_iso(row.updated_at),
        }
