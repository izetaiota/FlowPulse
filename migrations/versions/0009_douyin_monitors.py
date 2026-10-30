"""fp_douyin_monitors / fp_douyin_contents 抖音作品监控表

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from flowpulse.db.models import JSONVariant

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fp_douyin_monitors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="keyword"),
        sa.Column("target", sa.Text(), nullable=False, server_default=""),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("include_keywords", sa.Text(), nullable=False, server_default=""),
        sa.Column("exclude_keywords", sa.Text(), nullable=False, server_default=""),
        sa.Column("backfill_count", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scan_status", sa.String(length=16), nullable=False, server_default="never"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "fp_douyin_contents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("monitor_id", sa.Integer(), nullable=True),
        sa.Column("aweme_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("author", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("author_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_type", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("liked_count", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("create_time", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("extra", JSONVariant, nullable=False, server_default="{}"),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_fp_douyin_contents_monitor_seen", "fp_douyin_contents", ["monitor_id", "first_seen_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_fp_douyin_contents_monitor_seen", table_name="fp_douyin_contents")
    op.drop_table("fp_douyin_contents")
    op.drop_table("fp_douyin_monitors")
