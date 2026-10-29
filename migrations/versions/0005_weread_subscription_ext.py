"""fp_weread_subscriptions 扩展：RSS 定制 + 正文清洗 + 新文章推送开关

Revision ID: 0005
Revises: 0003
Create Date: 2026-10-29

（0004 为 RBAC 方案预留版本号，见 docs/RBAC_CASBIN_PLAN.md）
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0003"
branch_labels = None
depends_on = None

_COLUMNS = [
    sa.Column("rss_title", sa.Text(), nullable=False, server_default=""),
    sa.Column("rss_description", sa.Text(), nullable=False, server_default=""),
    sa.Column("rss_full_text", sa.Boolean(), nullable=True),
    sa.Column("rss_max_items", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("strip_keywords", sa.Text(), nullable=False, server_default=""),
    sa.Column("notify_new", sa.Boolean(), nullable=False, server_default=sa.true()),
]


def upgrade() -> None:
    with op.batch_alter_table("fp_weread_subscriptions") as batch:
        for column in _COLUMNS:
            batch.add_column(column)


def downgrade() -> None:
    with op.batch_alter_table("fp_weread_subscriptions") as batch:
        for column in reversed(_COLUMNS):
            batch.drop_column(column.name)
