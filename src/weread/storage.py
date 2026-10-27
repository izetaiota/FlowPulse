"""微信读书采集模块的文件存储（沿用项目的 JSON 原子写方案）。

目录结构（data_dir/weread/）：
  credential.json                 登录凭证
  subscriptions.json              订阅列表
  articles/<book_id>.json         每个公众号的文章列表（reviewId 去重）
"""

from __future__ import annotations

import json
from pathlib import Path

from weread.models import (
    CredentialState,
    MpArticle,
    MpSubscription,
    now_iso,
)


class WereadRepository:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "weread"
        self.articles_root = self.root / "articles"
        self.root.mkdir(parents=True, exist_ok=True)
        self.articles_root.mkdir(parents=True, exist_ok=True)

    # ---- 通用原子读写 ----

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    @staticmethod
    def _read_json(path: Path, default):
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    # ---- 凭证 ----

    def save_credential(self, cookie: str) -> CredentialState:
        state = CredentialState(cookie=cookie.strip())
        self._write_json(self.root / "credential.json", state.model_dump())
        return state

    def get_credential(self) -> CredentialState | None:
        data = self._read_json(self.root / "credential.json", None)
        if not data:
            return None
        try:
            return CredentialState.model_validate(data)
        except ValueError:
            return None

    def update_credential(self, state: CredentialState) -> None:
        self._write_json(self.root / "credential.json", state.model_dump())

    def delete_credential(self) -> bool:
        path = self.root / "credential.json"
        if path.is_file():
            path.unlink()
            return True
        return False

    # ---- 订阅 ----

    def list_subscriptions(self) -> list[MpSubscription]:
        data = self._read_json(self.root / "subscriptions.json", [])
        subs = []
        for item in data:
            try:
                subs.append(MpSubscription.model_validate(item))
            except ValueError:
                continue
        subs.sort(key=lambda s: s.added_at)
        return subs

    def get_subscription(self, book_id: str) -> MpSubscription | None:
        for sub in self.list_subscriptions():
            if sub.book_id == book_id:
                return sub
        return None

    def upsert_subscription(self, sub: MpSubscription) -> MpSubscription:
        subs = self.list_subscriptions()
        for index, existing in enumerate(subs):
            if existing.book_id == sub.book_id:
                subs[index] = sub
                break
        else:
            subs.append(sub)
        self._write_json(
            self.root / "subscriptions.json", [s.model_dump() for s in subs]
        )
        return sub

    def delete_subscription(self, book_id: str) -> bool:
        subs = self.list_subscriptions()
        remaining = [s for s in subs if s.book_id != book_id]
        if len(remaining) == len(subs):
            return False
        self._write_json(
            self.root / "subscriptions.json", [s.model_dump() for s in remaining]
        )
        path = self._article_path(book_id)
        if path.is_file():
            path.unlink()
        return True

    # ---- 文章 ----

    def _article_path(self, book_id: str) -> Path:
        safe = "".join(ch for ch in book_id if ch.isalnum() or ch in "_-")
        return self.articles_root / f"{safe}.json"

    def list_articles(self, book_id: str) -> list[MpArticle]:
        data = self._read_json(self._article_path(book_id), [])
        articles = []
        for item in data:
            try:
                articles.append(MpArticle.model_validate(item))
            except ValueError:
                continue
        articles.sort(key=lambda a: (a.publish_time, a.review_id), reverse=True)
        return articles

    def upsert_articles(self, book_id: str, incoming: list[MpArticle]) -> int:
        """按 reviewId 去重合并，返回新增数量。"""
        existing = self.list_articles(book_id)
        known = {a.review_id for a in existing}
        fresh = [a for a in incoming if a.review_id and a.review_id not in known]
        if not fresh:
            return 0
        merged = existing + fresh
        merged.sort(key=lambda a: (a.publish_time, a.review_id), reverse=True)
        self._write_json(
            self._article_path(book_id), [a.model_dump() for a in merged]
        )
        return len(fresh)

    def article_count(self, book_id: str) -> int:
        return len(self.list_articles(book_id))

    def refresh_subscription_stats(self, book_id: str, status: str, message: str = "") -> MpSubscription | None:
        sub = self.get_subscription(book_id)
        if not sub:
            return None
        sub.last_sync_at = now_iso()
        sub.last_sync_status = status
        sub.last_error = message
        sub.article_count = self.article_count(book_id)
        return self.upsert_subscription(sub)
