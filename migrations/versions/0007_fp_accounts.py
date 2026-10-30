"""fp_accounts 统一账号中心表

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from flowpulse.db.models import JSONVariant

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fp_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("account_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="managed"),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_ok", sa.Boolean(), nullable=True),
        sa.Column("last_check_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("extra", JSONVariant, nullable=False, server_default="{}"),
        sa.Column("credential_encrypted", sa.Text(), nullable=True),
        sa.Column("storage_state", JSONVariant, nullable=True),
        sa.Column("write_paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("risk_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_fp_accounts_platform_key", "fp_accounts", ["platform", "account_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_fp_accounts_platform_key", table_name="fp_accounts")
    op.drop_table("fp_accounts")
