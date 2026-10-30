"""数据库表定义（表名统一 fp_ 前缀；与文件存储 data/ 一一对应）。

表结构：
  fp_weread_subscriptions  订阅（book_id 主键）；删除时级联清文章与正文
  fp_weread_articles       文章（review_id 主键，reviewId 去重语义与文件版一致）
  fp_weread_contents       正文缓存（review_id 主键，独立成表避免列表查询拖大字段）
  fp_weread_credentials    凭证（单行 id=1；cookie 以 Fernet 密文落库）
  fp_weread_kv             调度器等键值状态（scheduler / cookie_refresher）
  fp_app_menus             侧栏菜单（数据驱动）
  fp_users                 Web 登录账号（单行 id=1；密码 PBKDF2 哈希，永不存明文）
  fp_notify_channels       通知渠道（页面管理的 webhook 地址）
  fp_notify_logs           通知发送记录（环形保留最近若干条）
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
    __tablename__ = "fp_weread_subscriptions"

    book_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    avatar: Mapped[str] = mapped_column(Text, default="")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str] = mapped_column(String(32), default="never")
    last_error: Mapped[str] = mapped_column(Text, default="")
    # RSS 输出定制（rss_full_text NULL = 跟随全局；rss_max_items 0 = 默认）
    rss_title: Mapped[str] = mapped_column(Text, default="")
    rss_description: Mapped[str] = mapped_column(Text, default="")
    rss_full_text: Mapped[bool | None] = mapped_column(Boolean)
    rss_max_items: Mapped[int] = mapped_column(Integer, default=0)
    # 正文清洗关键词（逗号分隔，叠加内置规则）
    strip_keywords: Mapped[str] = mapped_column(Text, default="")
    # 新文章推送开关
    notify_new: Mapped[bool] = mapped_column(Boolean, default=True)
    # 订阅级同步周期（分钟），0 = 跟随全局
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=0)


class WereadArticleRow(Base):
    __tablename__ = "fp_weread_articles"
    __table_args__ = (Index("ix_fp_weread_articles_book_publish", "book_id", "publish_time"),)

    review_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    book_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("fp_weread_subscriptions.book_id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(Text, default="")
    cover: Mapped[str] = mapped_column(Text, default="")
    digest: Mapped[str] = mapped_column(Text, default="")
    publish_time: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WereadContentRow(Base):
    __tablename__ = "fp_weread_contents"

    review_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("fp_weread_articles.review_id", ondelete="CASCADE"),
        primary_key=True,
    )
    book_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text, default="")
    content_html: Mapped[str] = mapped_column(Text, default="")
    publish_time: Mapped[int] = mapped_column(BigInteger, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WereadCredentialRow(Base):
    __tablename__ = "fp_weread_credentials"
    __table_args__ = (CheckConstraint("id = 1", name="ck_fp_weread_credentials_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    cookie: Mapped[str] = mapped_column(Text, default="")
    cookie_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid: Mapped[bool | None] = mapped_column(Boolean)
    last_error: Mapped[str] = mapped_column(Text, default="")


class WereadKvRow(Base):
    __tablename__ = "fp_weread_kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONVariant, default=dict)


class AppMenuRow(Base):
    """侧栏菜单（数据驱动，支持两级：parent 为空是顶级，否则为其 id）。"""

    __tablename__ = "fp_app_menus"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(64), default="")
    path: Mapped[str] = mapped_column(String(128), default="")
    icon: Mapped[str] = mapped_column(String(64), default="")
    parent: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)


class UserRow(Base):
    """Web 登录账号（单账号单行 id=1；密码只存 PBKDF2 哈希，永不落明文）。"""

    __tablename__ = "fp_users"
    __table_args__ = (CheckConstraint("id = 1", name="ck_fp_users_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    username: Mapped[str] = mapped_column(String(64), default="admin")
    password_hash: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class NotifyChannelRow(Base):
    """通知渠道（页面可管理；环境变量渠道不入库，运行时合并生效）。"""

    __tablename__ = "fp_notify_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NotifyLogRow(Base):
    """通知发送记录（按渠道逐条记录，超量裁剪保留最近部分）。"""

    __tablename__ = "fp_notify_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
