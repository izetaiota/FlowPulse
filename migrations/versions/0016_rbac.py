"""RBAC：fp_users 多行化、菜单 type/perm、fp_roles、fp_casbin_rule

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) fp_users 多行化
    op.execute("ALTER TABLE fp_users DROP CONSTRAINT IF EXISTS ck_fp_users_single_row")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_fp_users_username ON fp_users(username)")
    op.add_column("fp_users", sa.Column("status", sa.String(16), nullable=False, server_default="active"))

    # 2) 菜单加 type / perm
    op.add_column("fp_app_menus", sa.Column("type", sa.String(16), nullable=False, server_default="menu"))
    op.add_column("fp_app_menus", sa.Column("perm", sa.String(128), nullable=False, server_default=""))

    # 3) 角色元数据
    op.create_table(
        "fp_roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False, server_default=""),
        sa.Column("remark", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 4) casbin 策略
    op.create_table(
        "fp_casbin_rule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ptype", sa.String(8), nullable=False, server_default=""),
        sa.Column("v0", sa.String(128), nullable=False, server_default=""),
        sa.Column("v1", sa.String(128), nullable=False, server_default=""),
        sa.Column("v2", sa.String(128), nullable=False, server_default=""),
        sa.Column("v3", sa.String(128), nullable=False, server_default=""),
        sa.Column("v4", sa.String(128), nullable=False, server_default=""),
        sa.Column("v5", sa.String(128), nullable=False, server_default=""),
    )
    op.create_index("ix_fp_casbin_rule_ptype", "fp_casbin_rule", ["ptype", "v0", "v1"])

    # 5) 种子
    op.execute("INSERT INTO fp_roles (code, name, remark, status, created_at) VALUES ('admin', '超级管理员', '内置角色，拥有全部权限', 'active', now()) ON CONFLICT (code) DO NOTHING")
    op.execute("INSERT INTO fp_casbin_rule (ptype, v0, v1) VALUES ('p', 'admin', '*')")
    op.execute("INSERT INTO fp_casbin_rule (ptype, v0, v1) VALUES ('g', 'admin', 'admin')")


def downgrade() -> None:
    op.drop_table("fp_casbin_rule")
    op.drop_table("fp_roles")
    op.drop_column("fp_app_menus", "perm")
    op.drop_column("fp_app_menus", "type")
    op.drop_column("fp_users", "status")
