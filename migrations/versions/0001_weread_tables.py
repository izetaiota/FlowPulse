"""weread 模块初始表结构

Revision ID: 0001
Revises:
Create Date: 2026-10-28

与 flowpulse/db/models.py 对应；新模块建表请新增独立 revision。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weread_subscriptions",
        sa.Column("book_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("avatar", sa.Text(), nullable=False, server_default=""),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=32), nullable=False, server_default="never"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "weread_articles",
        sa.Column("review_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "book_id",
            sa.String(length=64),
            sa.ForeignKey("weread_subscriptions.book_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("link", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover", sa.Text(), nullable=False, server_default=""),
        sa.Column("digest", sa.Text(), nullable=False, server_default=""),
        sa.Column("publish_time", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_weread_articles_book_publish",
        "weread_articles",
        ["book_id", "publish_time"],
    )
    op.create_table(
        "weread_contents",
        sa.Column(
            "review_id",
            sa.String(length=128),
            sa.ForeignKey("weread_articles.review_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("book_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("publish_time", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "weread_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("cookie", sa.Text(), nullable=False, server_default=""),
        sa.Column("cookie_encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid", sa.Boolean(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.CheckConstraint("id = 1", name="ck_weread_credentials_single_row"),
    )
    op.create_table(
        "weread_kv",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column(
            "value",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("weread_kv")
    op.drop_table("weread_credentials")
    op.drop_table("weread_contents")
    op.drop_index("ix_weread_articles_book_publish", table_name="weread_articles")
    op.drop_table("weread_articles")
    op.drop_table("weread_subscriptions")
