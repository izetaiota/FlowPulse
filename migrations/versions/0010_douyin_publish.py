"""fp_douyin_publish_tasks 抖音发布队列表

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from flowpulse.db.models import JSONVariant

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fp_douyin_publish_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("desc", sa.Text(), nullable=False, server_default=""),
        sa.Column("topics", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_paths", JSONVariant, nullable=False, server_default="[]"),
        sa.Column("media_type", sa.String(length=16), nullable=False, server_default="video"),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="public"),
        sa.Column("allow_save", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fp_douyin_publish_tasks")
