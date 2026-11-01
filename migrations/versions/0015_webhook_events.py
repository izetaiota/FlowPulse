"""fp_webhook_subscriptions / fp_webhook_events 事件中心表

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from flowpulse.db.models import JSONVariant

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fp_webhook_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("secret", sa.Text(), nullable=False, server_default=""),
        sa.Column("events", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "fp_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", JSONVariant, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fp_webhook_events")
    op.drop_table("fp_webhook_subscriptions")
