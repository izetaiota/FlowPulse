"""表名统一 fp_ 前缀（rename 保留数据）+ 新增 fp_users 登录账号表

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29

- 旧表 weread_* / app_menus 重命名为 fp_*（ALTER TABLE RENAME，数据与约束保留）
- 新增 fp_users（单行 id=1，password_hash 存 PBKDF2 哈希）
- 应用启动时的 ensure_tables 只建缺失表，不会自动重命名——存量库必须先跑本迁移
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# (旧表名, 新表名)；rename 后 PG 外键引用自动跟随新表名
_TABLE_RENAMES = [
    ("weread_subscriptions", "fp_weread_subscriptions"),
    ("weread_articles", "fp_weread_articles"),
    ("weread_contents", "fp_weread_contents"),
    ("weread_credentials", "fp_weread_credentials"),
    ("weread_kv", "fp_weread_kv"),
    ("app_menus", "fp_app_menus"),
]


def upgrade() -> None:
    for old_name, new_name in _TABLE_RENAMES:
        op.rename_table(old_name, new_name)
    op.execute(
        "ALTER INDEX ix_weread_articles_book_publish"
        " RENAME TO ix_fp_weread_articles_book_publish"
    )
    op.create_table(
        "fp_users",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("username", sa.String(length=64), nullable=False, server_default="admin"),
        sa.Column("password_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_fp_users_single_row"),
    )


def downgrade() -> None:
    op.drop_table("fp_users")
    op.execute(
        "ALTER INDEX ix_fp_weread_articles_book_publish"
        " RENAME TO ix_weread_articles_book_publish"
    )
    for old_name, new_name in reversed(_TABLE_RENAMES):
        op.rename_table(new_name, old_name)
