"""微信读书采集模块的文件存储（沿用项目的 JSON 原子写方案）。

目录结构（data_dir/weread/）：
  credential.json                 登录凭证
  subscriptions.json              订阅列表
  articles/<book_id>.json         每个公众号的文章列表（reviewId 去重）
"""

from __future__ import annotations

from pathlib import Path

from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.modules.weread.models import (
    CredentialState,
    MpArticle,
    MpArticleContent,
    MpSubscription,
    article_sort_key,
    now_iso,
)

DEFAULT_SCHEDULER_STATE: dict = {
    "enabled": False,
    "interval_minutes": 0,
    "running": False,
    "last_run_at": None,
    "last_result": None,
}

DEFAULT_COOKIE_REFRESHER_STATE: dict = {
    "enabled": False,
    "interval_hours": 0,
    "running": False,
    "last_run_at": None,
    "last_result": None,
}


class WereadRepository:
    def __init__(self, data_dir: Path, credential_key: str = ""):
        self.root = data_dir / "weread"
        self.articles_root = self.root / "articles"
        self.contents_root = self.root / "contents"
        self.root.mkdir(parents=True, exist_ok=True)
        self.articles_root.mkdir(parents=True, exist_ok=True)
        self.contents_root.mkdir(parents=True, exist_ok=True)
        self._cipher = self._init_credential_cipher(credential_key)

    # ---- 调度器状态 ----

    def load_scheduler_state(self) -> dict:
        return self._read_json(self.root / "scheduler.json", dict(DEFAULT_SCHEDULER_STATE))

    def save_scheduler_state(self, state: dict) -> None:
        self._write_json(self.root / "scheduler.json", state)

    # ---- Cookie 续期状态 ----

    def load_cookie_refresher_state(self) -> dict:
        return self._read_json(
            self.root / "cookie_refresher.json", dict(DEFAULT_COOKIE_REFRESHER_STATE)
        )

    def save_cookie_refresher_state(self, state: dict) -> None:
        self._write_json(self.root / "cookie_refresher.json", state)

    # ---- 通用原子读写 ----

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        atomic_write_json(path, payload)

    @staticmethod
    def _read_json(path: Path, default):
        return read_json(path, default)

    # ---- 凭证 ----

    def _init_credential_cipher(self, credential_key: str):
        """Cookie 静态加密（Fernet）：优先用外部密钥，其次 data 目录内密钥文件。

        未安装 cryptography 时降级为明文存储（功能不受影响，仅静态保护缺失）。
        """
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            return None
        key = (credential_key or "").strip()
        if key:
            return Fernet(key.encode())  # 外部密钥非法时直接报错，避免静默降级
        key_path = self.root / ".credential_key"
        try:
            key = key_path.read_text(encoding="utf-8").strip()
        except OSError:
            key = Fernet.generate_key().decode()
            key_path.write_text(key, encoding="utf-8")
        return Fernet(key.encode())

    def _seal(self, payload: dict) -> dict:
        if self._cipher and payload.get("cookie"):
            payload = dict(payload)
            payload["cookie"] = self._cipher.encrypt(payload["cookie"].encode()).decode()
            payload["cookie_encrypted"] = True
        return payload

    def _unseal(self, data) -> dict | None:
        if not data:
            return None
        if not data.get("cookie_encrypted"):
            return data  # 旧版明文，读取不受影响，下次保存自动升级为加密
        if not self._cipher:
            return None  # 密钥不可用（丢失/更换），凭证无法解密
        try:
            data = dict(data)
            data["cookie"] = self._cipher.decrypt(data["cookie"].encode()).decode()
        except Exception:
            return None
        data.pop("cookie_encrypted", None)
        return data

    def save_credential(self, cookie: str) -> CredentialState:
        state = CredentialState(cookie=cookie.strip())
        self._write_json(self.root / "credential.json", self._seal(state.model_dump()))
        return state

    def get_credential(self) -> CredentialState | None:
        data = self._unseal(self._read_json(self.root / "credential.json", None))
        if not data:
            return None
        try:
            return CredentialState.model_validate(data)
        except ValueError:
            return None

    def update_credential(self, state: CredentialState) -> None:
        self._write_json(self.root / "credential.json", self._seal(state.model_dump()))

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
        # 文章列表与已抓正文缓存一并清理，避免遗留孤儿文件
        for article in self.list_articles(book_id):
            content_path = self._content_path(article.review_id)
            if content_path.is_file():
                content_path.unlink()
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
        articles.sort(key=article_sort_key, reverse=True)
        return articles

    def upsert_articles(self, book_id: str, incoming: list[MpArticle]) -> int:
        """按 reviewId 去重合并，返回新增数量。"""
        existing = self.list_articles(book_id)
        known = {a.review_id for a in existing}
        fresh = [a for a in incoming if a.review_id and a.review_id not in known]
        if not fresh:
            return 0
        merged = existing + fresh
        merged.sort(key=article_sort_key, reverse=True)
        self._write_json(
            self._article_path(book_id), [a.model_dump() for a in merged]
        )
        return len(fresh)

    def set_article_digest(self, book_id: str, review_id: str, digest: str) -> bool:
        """回填文章摘要（cover 通道不带摘要，读到正文后补，供 RSS description 用）。"""
        digest = (digest or "").strip()
        if not digest:
            return False
        articles = self.list_articles(book_id)
        for article in articles:
            if article.review_id == review_id and article.digest != digest:
                article.digest = digest
                self._write_json(
                    self._article_path(book_id), [a.model_dump() for a in articles]
                )
                return True
        return False

    def article_count(self, book_id: str) -> int:
        return len(self.list_articles(book_id))

    def set_article_publish_time(self, book_id: str, review_id: str, publish_time: int) -> bool:
        """回填文章发布时间（cover 通道拿不到，读到原文页后补记）。"""
        articles = self.list_articles(book_id)
        for article in articles:
            if article.review_id == review_id and article.publish_time != publish_time:
                article.publish_time = publish_time
                self._write_json(
                    self._article_path(book_id), [a.model_dump() for a in articles]
                )
                return True
        return False

    def refresh_subscription_stats(self, book_id: str, status: str, message: str = "") -> MpSubscription | None:
        sub = self.get_subscription(book_id)
        if not sub:
            return None
        sub.last_sync_at = now_iso()
        sub.last_sync_status = status
        sub.last_error = message
        sub.article_count = self.article_count(book_id)
        return self.upsert_subscription(sub)

    # ---- 文章正文 ----

    def _content_path(self, review_id: str) -> Path:
        safe = "".join(ch for ch in review_id if ch.isalnum() or ch in "_-")
        return self.contents_root / f"{safe}.json"

    def get_content(self, review_id: str) -> MpArticleContent | None:
        data = self._read_json(self._content_path(review_id), None)
        if not data:
            return None
        try:
            return MpArticleContent.model_validate(data)
        except ValueError:
            return None

    def save_content(self, content: MpArticleContent) -> MpArticleContent:
        self._write_json(self._content_path(content.review_id), content.model_dump())
        return content
