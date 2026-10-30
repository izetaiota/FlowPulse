"""订阅级同步周期 + 通知渠道与发送记录表

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fp_weread_subscriptions") as batch:
        batch.add_column(
            sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_table(
        "fp_notify_channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "fp_notify_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fp_notify_logs")
    op.drop_table("fp_notify_channels")
    with op.batch_alter_table("fp_weread_subscriptions") as batch:
        batch.drop_column("sync_interval_minutes")
