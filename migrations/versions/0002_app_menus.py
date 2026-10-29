"""app_menus 菜单表（侧栏菜单数据驱动）

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_menus",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("path", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("icon", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("parent", sa.String(length=64), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_table("app_menus")
