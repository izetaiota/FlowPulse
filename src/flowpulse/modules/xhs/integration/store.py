from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from flowpulse.core.crypto import CredentialCipher
from flowpulse.modules.xhs.integration.models import JobRecord, utc_now


class CookieStore:
    """Persist authenticated cookie strings per platform to a JSON file.

    Cookie 值以 Fernet 静态加密落盘（密钥自动生成于 xhs/.credential_key，
    或由外部传入）；旧版明文读取兼容、下次保存自动升级为密文。
    """

    def __init__(self, root: Path, credential_key: str = ""):
        self.path = root / "xhs" / "cookies.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cipher = CredentialCipher(
            credential_key, key_file=root / "xhs" / ".credential_key"
        )
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        if value.startswith("gAAA"):
            if not self._cipher.available:
                return None
            try:
                return self._cipher.decrypt(value)
            except Exception:
                return None
        return value  # 旧版明文

    def get(self, platform: str) -> str | None:
        with self._lock:
            return self._decrypt(self._read().get(platform))

    def set(self, platform: str, cookies: str) -> None:
        with self._lock:
            data = self._read()
            data[platform] = (
                self._cipher.encrypt(cookies) if self._cipher.available else cookies
            )
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def clear(self, platform: str) -> None:
        with self._lock:
            data = self._read()
            data.pop(platform, None)
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )


class LoginSessionRegistry:
    """In-memory registry holding interactive login flow state (qrcode / phone).

    The underlying XHS login objects own a live curl_cffi session and mutable
    cookie state, so they cannot be serialised between requests. This keeps
    them in process, matching the service's single-process task model.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, session_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._sessions[session_id] = payload

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


class JobRepository:
    """File-backed repository for async scrape/download jobs."""

    def __init__(self, root: Path):
        self.root = root / "xhs" / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def save(self, record: JobRecord) -> JobRecord:
        record.updated_at = utc_now()
        directory = self.job_dir(record.id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "job.json").write_text(
            record.model_dump_json(indent=2), encoding="utf-8"
        )
        return record

    def get(self, job_id: str) -> JobRecord | None:
        path = self.job_dir(job_id) / "job.json"
        if not path.exists():
            return None
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[JobRecord]:
        records: list[JobRecord] = []
        for path in self.root.glob("*/job.json"):
            try:
                records.append(JobRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records
