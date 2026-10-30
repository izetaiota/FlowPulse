"""fp_xhs_dm_drafts 增加 error / sent_at 列（T4.2 发送闭环）

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fp_xhs_dm_drafts", sa.Column("error", sa.Text(), nullable=False, server_default=""))
    op.add_column("fp_xhs_dm_drafts", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("fp_xhs_dm_drafts", "sent_at")
    op.drop_column("fp_xhs_dm_drafts", "error")
