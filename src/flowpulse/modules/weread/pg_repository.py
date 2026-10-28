"""weread 模块的 PostgreSQL（SQLAlchemy 同步）仓储实现。

与文件版 `storage.WereadRepository` 接口完全对等（service/scheduler/refresher/api
无感知切换）。DTO 仍复用 pydantic 模型；cookie 沿用 core/crypto 的 Fernet 加密，
密钥文件与文件版共用（data/weread/.credential_key），双后端切换/迁移时密文互通。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.core.crypto import CredentialCipher
from flowpulse.db.models import (
    WereadArticleRow,
    WereadContentRow,
    WereadCredentialRow,
    WereadKvRow,
    WereadSubscriptionRow,
)
from flowpulse.modules.weread.models import (
    CredentialState,
    MpArticle,
    MpArticleContent,
    MpSubscription,
    article_sort_key,
    now_iso,
)
from flowpulse.modules.weread.storage import (
    DEFAULT_COOKIE_REFRESHER_STATE,
    DEFAULT_SCHEDULER_STATE,
)

SCHEDULER_KEY = "scheduler"
COOKIE_REFRESHER_KEY = "cookie_refresher"


def _to_utc(dt: datetime | None) -> datetime | None:
    """sqlite 返回 naive datetime，统一按 UTC 处理。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _to_iso(dt: datetime | None) -> str | None:
    utc = _to_utc(dt)
    return utc.isoformat(timespec="seconds") if utc else None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class PgWereadRepository:
    def __init__(
        self,
        sessionmaker_: sessionmaker[Session],
        credential_key: str = "",
        key_file: Path | None = None,
    ):
        self._sessionmaker = sessionmaker_
        self._cipher = CredentialCipher(credential_key, key_file=key_file)

    # ---- kv 状态（调度器 / 续期器） ----

    def _load_kv(self, key: str, default: dict) -> dict:
        with self._sessionmaker() as session:
            row = session.get(WereadKvRow, key)
            return dict(row.value) if row else dict(default)

    def _save_kv(self, key: str, value: dict) -> None:
        with self._sessionmaker() as session:
            row = session.get(WereadKvRow, key)
            if row:
                row.value = value
            else:
                session.add(WereadKvRow(key=key, value=value))
            session.commit()

    def load_scheduler_state(self) -> dict:
        return self._load_kv(SCHEDULER_KEY, DEFAULT_SCHEDULER_STATE)

    def save_scheduler_state(self, state: dict) -> None:
        self._save_kv(SCHEDULER_KEY, state)

    def load_cookie_refresher_state(self) -> dict:
        return self._load_kv(COOKIE_REFRESHER_KEY, DEFAULT_COOKIE_REFRESHER_STATE)

    def save_cookie_refresher_state(self, state: dict) -> None:
        self._save_kv(COOKIE_REFRESHER_KEY, state)

    # ---- 凭证 ----

    def save_credential(self, cookie: str) -> CredentialState:
        state = CredentialState(cookie=cookie.strip())
        self.update_credential(state)
        return state

    def get_credential(self) -> CredentialState | None:
        with self._sessionmaker() as session:
            row = session.get(WereadCredentialRow, 1)
        if not row:
            return None
        data = self._cipher.unseal(
            {"cookie": row.cookie, "cookie_encrypted": row.cookie_encrypted}
        )
        if not data:
            return None
        try:
            return CredentialState(
                cookie=data["cookie"],
                saved_at=_to_iso(row.saved_at) or now_iso(),
                last_validated_at=_to_iso(row.last_validated_at),
                valid=row.valid,
                last_error=row.last_error,
            )
        except ValueError:
            return None

    def update_credential(self, state: CredentialState) -> None:
        sealed = self._cipher.seal(state.model_dump())
        with self._sessionmaker() as session:
            row = session.get(WereadCredentialRow, 1)
            if row:
                row.cookie = sealed["cookie"]
                row.cookie_encrypted = sealed.get("cookie_encrypted", False)
                row.saved_at = _parse_iso(sealed["saved_at"]) or datetime.now(timezone.utc)
                row.last_validated_at = _parse_iso(sealed.get("last_validated_at"))
                row.valid = sealed.get("valid")
                row.last_error = sealed.get("last_error", "")
            else:
                session.add(
                    WereadCredentialRow(
                        id=1,
                        cookie=sealed["cookie"],
                        cookie_encrypted=sealed.get("cookie_encrypted", False),
                        saved_at=_parse_iso(sealed["saved_at"]) or datetime.now(timezone.utc),
                        last_validated_at=_parse_iso(sealed.get("last_validated_at")),
                        valid=sealed.get("valid"),
                        last_error=sealed.get("last_error", ""),
                    )
                )
            session.commit()

    def delete_credential(self) -> bool:
        with self._sessionmaker() as session:
            row = session.get(WereadCredentialRow, 1)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    # ---- 订阅 ----

    @staticmethod
    def _sub_dto(row: WereadSubscriptionRow, article_count: int = 0) -> MpSubscription:
        return MpSubscription(
            book_id=row.book_id,
            name=row.name,
            avatar=row.avatar,
            added_at=_to_iso(row.added_at) or now_iso(),
            last_sync_at=_to_iso(row.last_sync_at),
            last_sync_status=row.last_sync_status,
            last_error=row.last_error,
            article_count=article_count,
        )

    def list_subscriptions(self) -> list[MpSubscription]:
        with self._sessionmaker() as session:
            rows = session.execute(
                select(WereadSubscriptionRow).order_by(WereadSubscriptionRow.added_at)
            ).scalars().all()
            counts = dict(
                session.execute(
                    select(WereadArticleRow.book_id, func.count()).group_by(
                        WereadArticleRow.book_id
                    )
                ).all()
            )
        return [self._sub_dto(row, counts.get(row.book_id, 0)) for row in rows]

    def get_subscription(self, book_id: str) -> MpSubscription | None:
        with self._sessionmaker() as session:
            row = session.get(WereadSubscriptionRow, book_id)
            if not row:
                return None
            count = session.execute(
                select(func.count())
                .select_from(WereadArticleRow)
                .where(WereadArticleRow.book_id == book_id)
            ).scalar_one()
        return self._sub_dto(row, count)

    def upsert_subscription(self, sub: MpSubscription) -> MpSubscription:
        with self._sessionmaker() as session:
            row = session.get(WereadSubscriptionRow, sub.book_id)
            added_at = _parse_iso(sub.added_at) or datetime.now(timezone.utc)
            last_sync_at = _parse_iso(sub.last_sync_at)
            if row:
                row.name, row.avatar = sub.name, sub.avatar
                row.added_at, row.last_sync_at = added_at, last_sync_at
                row.last_sync_status, row.last_error = sub.last_sync_status, sub.last_error
            else:
                session.add(
                    WereadSubscriptionRow(
                        book_id=sub.book_id,
                        name=sub.name,
                        avatar=sub.avatar,
                        added_at=added_at,
                        last_sync_at=last_sync_at,
                        last_sync_status=sub.last_sync_status,
                        last_error=sub.last_error,
                    )
                )
            session.commit()
        return sub

    def delete_subscription(self, book_id: str) -> bool:
        """删除订阅并清理文章与正文缓存（显式删子表，不依赖后端外键强制）。"""
        with self._sessionmaker() as session:
            row = session.get(WereadSubscriptionRow, book_id)
            if not row:
                return False
            session.execute(
                delete(WereadContentRow).where(WereadContentRow.book_id == book_id)
            )
            session.execute(
                delete(WereadArticleRow).where(WereadArticleRow.book_id == book_id)
            )
            session.delete(row)
            session.commit()
            return True

    # ---- 文章 ----

    @staticmethod
    def _article_dto(row: WereadArticleRow) -> MpArticle:
        return MpArticle(
            review_id=row.review_id,
            book_id=row.book_id,
            title=row.title,
            link=row.link,
            cover=row.cover,
            digest=row.digest,
            publish_time=row.publish_time,
            created_at=_to_iso(row.created_at) or now_iso(),
        )

    def list_articles(self, book_id: str) -> list[MpArticle]:
        with self._sessionmaker() as session:
            rows = (
                session.execute(
                    select(WereadArticleRow).where(WereadArticleRow.book_id == book_id)
                )
                .scalars()
                .all()
            )
        articles = [self._article_dto(row) for row in rows]
        # 与文件版语义一致：发布时间缺省（0）的文章按入库时间兜底排序
        articles.sort(key=article_sort_key, reverse=True)
        return articles

    def upsert_articles(self, book_id: str, incoming: list[MpArticle]) -> int:
        """按 reviewId 去重合并，返回新增数量。"""
        with self._sessionmaker() as session:
            existing_ids = set(
                session.execute(
                    select(WereadArticleRow.review_id).where(
                        WereadArticleRow.book_id == book_id
                    )
                )
                .scalars()
                .all()
            )
            fresh = [
                WereadArticleRow(
                    review_id=a.review_id,
                    book_id=book_id,
                    title=a.title,
                    link=a.link,
                    cover=a.cover,
                    digest=a.digest,
                    publish_time=a.publish_time,
                    created_at=_parse_iso(a.created_at) or datetime.now(timezone.utc),
                )
                for a in incoming
                if a.review_id and a.review_id not in existing_ids
            ]
            session.add_all(fresh)
            session.commit()
            return len(fresh)

    def article_count(self, book_id: str) -> int:
        with self._sessionmaker() as session:
            return session.execute(
                select(func.count())
                .select_from(WereadArticleRow)
                .where(WereadArticleRow.book_id == book_id)
            ).scalar_one()

    def set_article_publish_time(self, book_id: str, review_id: str, publish_time: int) -> bool:
        with self._sessionmaker() as session:
            row = session.get(WereadArticleRow, review_id)
            if not row or row.book_id != book_id or row.publish_time == publish_time:
                return False
            row.publish_time = publish_time
            session.commit()
            return True

    def set_article_digest(self, book_id: str, review_id: str, digest: str) -> bool:
        digest = (digest or "").strip()
        if not digest:
            return False
        with self._sessionmaker() as session:
            row = session.get(WereadArticleRow, review_id)
            if not row or row.book_id != book_id or row.digest == digest:
                return False
            row.digest = digest
            session.commit()
            return True

    def refresh_subscription_stats(
        self, book_id: str, status: str, message: str = ""
    ) -> MpSubscription | None:
        with self._sessionmaker() as session:
            row = session.get(WereadSubscriptionRow, book_id)
            if not row:
                return None
            row.last_sync_at = datetime.now(timezone.utc)
            row.last_sync_status = status
            row.last_error = message
            session.commit()
        return self.get_subscription(book_id)

    # ---- 文章正文 ----

    def get_content(self, review_id: str) -> MpArticleContent | None:
        with self._sessionmaker() as session:
            row = session.get(WereadContentRow, review_id)
            if not row:
                return None
            return MpArticleContent(
                review_id=row.review_id,
                book_id=row.book_id,
                title=row.title,
                content_html=row.content_html,
                publish_time=row.publish_time,
                fetched_at=_to_iso(row.fetched_at) or now_iso(),
            )

    def save_content(self, content: MpArticleContent) -> MpArticleContent:
        with self._sessionmaker() as session:
            row = session.get(WereadContentRow, content.review_id)
            fetched_at = _parse_iso(content.fetched_at) or datetime.now(timezone.utc)
            if row:
                row.book_id, row.title = content.book_id, content.title
                row.content_html, row.publish_time = (
                    content.content_html,
                    content.publish_time,
                )
                row.fetched_at = fetched_at
            else:
                session.add(
                    WereadContentRow(
                        review_id=content.review_id,
                        book_id=content.book_id,
                        title=content.title,
                        content_html=content.content_html,
                        publish_time=content.publish_time,
                        fetched_at=fetched_at,
                    )
                )
            session.commit()
        return content
