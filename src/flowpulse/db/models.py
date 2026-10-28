"""weread 模块的数据库表定义（与文件存储 data/weread/ 一一对应）。

表结构：
  weread_subscriptions  订阅（book_id 主键）；删除时级联清文章与正文
  weread_articles       文章（review_id 主键，reviewId 去重语义与文件版一致）
  weread_contents       正文缓存（review_id 主键，独立成表避免列表查询拖大字段）
  weread_credentials    凭证（单行 id=1；cookie 以 Fernet 密文落库）
  weread_kv             调度器等键值状态（scheduler / cookie_refresher）
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from flowpulse.db.base import Base

# sqlite 兼容：PG 上用 JSONB，其他后端退普通 JSON
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WereadSubscriptionRow(Base):
    __tablename__ = "weread_subscriptions"

    book_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    avatar: Mapped[str] = mapped_column(Text, default="")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str] = mapped_column(String(32), default="never")
    last_error: Mapped[str] = mapped_column(Text, default="")


class WereadArticleRow(Base):
    __tablename__ = "weread_articles"
    __table_args__ = (Index("ix_weread_articles_book_publish", "book_id", "publish_time"),)

    review_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    book_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("weread_subscriptions.book_id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(Text, default="")
    cover: Mapped[str] = mapped_column(Text, default="")
    digest: Mapped[str] = mapped_column(Text, default="")
    publish_time: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WereadContentRow(Base):
    __tablename__ = "weread_contents"

    review_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("weread_articles.review_id", ondelete="CASCADE"),
        primary_key=True,
    )
    book_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text, default="")
    content_html: Mapped[str] = mapped_column(Text, default="")
    publish_time: Mapped[int] = mapped_column(BigInteger, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WereadCredentialRow(Base):
    __tablename__ = "weread_credentials"
    __table_args__ = (CheckConstraint("id = 1", name="ck_weread_credentials_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    cookie: Mapped[str] = mapped_column(Text, default="")
    cookie_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid: Mapped[bool | None] = mapped_column(Boolean)
    last_error: Mapped[str] = mapped_column(Text, default="")


class WereadKvRow(Base):
    __tablename__ = "weread_kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONVariant, default=dict)
