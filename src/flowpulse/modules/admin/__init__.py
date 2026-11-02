# -*- coding: utf-8 -*-
"""RBAC 管理与 session 扩展（阶段 2）：用户/角色 CRUD + 权限码 + 角色过滤菜单。

依赖 core/rbac.py 的 enforcer；session 接口扩展 roles/perms/menus。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.core.auth import _state, verify_token
from flowpulse.core.crypto import CredentialCipher
from flowpulse.core.rbac import ADMIN_ROLE, CurrentUser, resolve_user
from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.db.models import RoleRow, UserRow

router = APIRouter(prefix="/api/admin", tags=["rbac"])


def get_rbac_deps() -> tuple[Any, Any]:
    """返回 (enforcer, user_store_sessionmaker)；由 runtime override 注入。"""
    raise RuntimeError("Dependency override is not configured")


def get_current_user_rbac(request: Request, deps=Depends(get_rbac_deps)) -> CurrentUser:
    """从 Bearer token 解 username → resolve_user（roles + perms）。"""
    token = request.headers.get("authorization", "")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    token = token or request.query_params.get("token", "")
    username = verify_token(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    enforcer, _ = deps
    if enforcer is None:
        # pycasbin 未安装：降级为仅登录校验（无角色/权限）
        return CurrentUser(username=username, roles=[], perms=["*"], enforcer=None)
    return resolve_user(enforcer, username)


def require_admin(user: CurrentUser = Depends(get_current_user_rbac)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    return user


# ---- 用户管理 ----


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    roles: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=128)
    roles: list[str] | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


def _hash_password(password: str) -> str:
    import hashlib
    import os

    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return f"{salt.hex()}${digest.hex()}"


def _verify_pw(password: str, stored: str) -> bool:
    import hashlib

    try:
        salt_hex, digest_hex = stored.split("$", 1)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 100_000)
        return digest.hex() == digest_hex
    except (ValueError, TypeError):
        return False


@router.get("/users")
def list_users(_admin: CurrentUser = Depends(require_admin)) -> dict:
    _, sessionmaker_ = get_rbac_deps()
    enforcer, _ = get_rbac_deps()
    users = []
    if sessionmaker_ is not None:
        with sessionmaker_() as session:
            rows = session.execute(select(UserRow).order_by(UserRow.id)).scalars().all()
            for row in rows:
                users.append({
                    "id": row.id, "username": row.username, "status": row.status,
                    "roles": enforcer.get_roles_for_user(row.username),
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                })
    else:
        from flowpulse.core.auth import AuthUserStore

        store = _state.get("store")
        if store and hasattr(store, "list_all"):
            for user in store.list_all():
                users.append({**user, "roles": enforcer.get_roles_for_user(user["username"])})
    return {"users": users}


@router.post("/users", status_code=201)
def create_user(request: UserCreate, _admin: CurrentUser = Depends(require_admin)) -> dict:
    enforcer, sessionmaker_ = get_rbac_deps()
    # 检查重名
    if sessionmaker_ is not None:
        with sessionmaker_() as session:
            existing = session.execute(select(UserRow).where(UserRow.username == request.username)).scalars().first()
            if existing:
                raise HTTPException(status_code=409, detail=f"用户已存在：{request.username}")
            session.add(UserRow(
                username=request.username,
                password_hash=_hash_password(request.password),
                status="active",
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()
    else:
        store = _state.get("store")
        if store and store.load_by_username(request.username):
            raise HTTPException(status_code=409, detail=f"用户已存在：{request.username}")
        store.create_user(request.username, _hash_password(request.password))
    # 挂角色
    for role in request.roles:
        enforcer.add_role_for_user(request.username, role)
    return {"username": request.username, "created": True}


@router.put("/users/{username}")
def update_user(username: str, request: UserUpdate, _admin: CurrentUser = Depends(require_admin)) -> dict:
    enforcer, sessionmaker_ = get_rbac_deps()
    if sessionmaker_ is not None:
        with sessionmaker_() as session:
            row = session.execute(select(UserRow).where(UserRow.username == username)).scalars().first()
            if row is None:
                raise HTTPException(status_code=404, detail=f"用户不存在：{username}")
            if request.password:
                row.password_hash = _hash_password(request.password)
            if request.status:
                row.status = request.status
            session.commit()
    if request.roles is not None:
        # 先清旧角色再挂新
        for old in enforcer.get_roles_for_user(username):
            enforcer.delete_role_for_user(username, old)
        for role in request.roles:
            enforcer.add_role_for_user(username, role)
    return {"username": username, "updated": True}


@router.delete("/users/{username}")
def delete_user(username: str, _admin: CurrentUser = Depends(require_admin)) -> dict:
    if username == "admin":
        raise HTTPException(status_code=400, detail="不能删除内置 admin 账号")
    enforcer, sessionmaker_ = get_rbac_deps()
    if sessionmaker_ is not None:
        with sessionmaker_() as session:
            row = session.execute(select(UserRow).where(UserRow.username == username)).scalars().first()
            if row is None:
                raise HTTPException(status_code=404, detail=f"用户不存在：{username}")
            session.delete(row)
            session.commit()
    for old in enforcer.get_roles_for_user(username):
        enforcer.delete_role_for_user(username, old)
    return {"deleted": True}


# ---- 角色管理 ----


class RoleCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern="^[a-z][a-z0-9_]*$")
    name: str = Field(default="", max_length=64)
    remark: str = Field(default="", max_length=500)
    perms: list[str] = Field(default_factory=list)   # 权限码列表


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=500)
    perms: list[str] | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


@router.get("/roles")
def list_roles(_admin: CurrentUser = Depends(require_admin)) -> dict:
    enforcer, sessionmaker_ = get_rbac_deps()
    roles = []
    if sessionmaker_ is not None:
        with sessionmaker_() as session:
            rows = session.execute(select(RoleRow).order_by(RoleRow.id)).scalars().all()
            for row in rows:
                roles.append({
                    "id": row.id, "code": row.code, "name": row.name,
                    "remark": row.remark, "status": row.status,
                    "perms": sorted(enforcer.get_permissions_for_user(row.code) and
                                    [p[1] for p in enforcer.get_permissions_for_user(row.code)] or []),
                    "users": enforcer.get_users_for_role(row.code),
                })
    return {"roles": roles}


@router.post("/roles", status_code=201)
def create_role(request: RoleCreate, _admin: CurrentUser = Depends(require_admin)) -> dict:
    enforcer, sessionmaker_ = get_rbac_deps()
    if sessionmaker_ is not None:
        with sessionmaker_() as session:
            existing = session.execute(select(RoleRow).where(RoleRow.code == request.code)).scalars().first()
            if existing:
                raise HTTPException(status_code=409, detail=f"角色已存在：{request.code}")
            session.add(RoleRow(
                code=request.code, name=request.name or request.code,
                remark=request.remark, status="active",
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()
    # 写 p 策略
    for perm in request.perms:
        enforcer.add_permission_for_user(request.code, perm)
    return {"code": request.code, "created": True}


@router.put("/roles/{code}")
def update_role(code: str, request: RoleUpdate, _admin: CurrentUser = Depends(require_admin)) -> dict:
    enforcer, sessionmaker_ = get_rbac_deps()
    if sessionmaker_ is not None:
        with sessionmaker_() as session:
            row = session.execute(select(RoleRow).where(RoleRow.code == code)).scalars().first()
            if row is None:
                raise HTTPException(status_code=404, detail=f"角色不存在：{code}")
            if request.name is not None:
                row.name = request.name
            if request.remark is not None:
                row.remark = request.remark
            if request.status is not None:
                row.status = request.status
            session.commit()
    if request.perms is not None:
        # 清旧 p 策略再写新
        enforcer.delete_permissions_for_user(code)
        for perm in request.perms:
            enforcer.add_permission_for_user(code, perm)
    return {"code": code, "updated": True}


@router.delete("/roles/{code}")
def delete_role(code: str, _admin: CurrentUser = Depends(require_admin)) -> dict:
    if code == ADMIN_ROLE:
        raise HTTPException(status_code=400, detail="不能删除内置 admin 角色")
    enforcer, _ = get_rbac_deps()
    users = enforcer.get_users_for_role(code)
    if users:
        raise HTTPException(status_code=400, detail=f"角色仍有 {len(users)} 个用户挂载，请先解绑")
    enforcer.delete_role(code)
    _, sessionmaker_ = get_rbac_deps()
    if sessionmaker_ is not None:
        with sessionmaker_() as session:
            row = session.execute(select(RoleRow).where(RoleRow.code == code)).scalars().first()
            if row:
                session.delete(row)
                session.commit()
    return {"deleted": True}


@router.get("/perm-codes")
def list_perm_codes(_admin: CurrentUser = Depends(require_admin)) -> dict:
    """从菜单树导出全部可分配权限码（角色编辑页勾选用）。"""
    from flowpulse.modules.menu import get_menu_repository
    from fastapi import Depends as _Depends

    # 菜单仓储由 dependency_overrides 注入
    return {"codes": _extract_perm_codes_from_menus()}


def _extract_perm_codes_from_menus() -> list[str]:
    """从 DEFAULT_MENUS 或实际菜单表提取权限码。"""
    from flowpulse.modules.menu import DEFAULT_MENUS

    codes: set[str] = set()
    for item in DEFAULT_MENUS:
        perm = item.get("perm", "")
        if perm:
            codes.add(perm)
    return sorted(codes)
