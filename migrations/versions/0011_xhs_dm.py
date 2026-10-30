"""fp_xhs_dm_rules / fp_xhs_dm_drafts 小红书私信规则与审核草稿表

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fp_xhs_dm_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("keywords", sa.Text(), nullable=False, server_default=""),
        sa.Column("reply_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "fp_xhs_dm_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conv_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("peer_uid", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("peer_nickname", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("last_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("rule_name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("suggested_reply", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fp_xhs_dm_drafts")
    op.drop_table("fp_xhs_dm_rules")
