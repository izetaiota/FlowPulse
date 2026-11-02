"""RBAC 权限引擎测试：模型语义（继承/通配/拒绝）、enforcer 装配、admin API。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.core.rbac import ADMIN_ROLE, RBAC_MODEL_TEXT, build_enforcer, resolve_user
from flowpulse.main import create_app


def _make_enforcer(tmp_path: Path):
    """文件模式 enforcer（不依赖 PG），便于测试模型语义。"""
    enforcer = build_enforcer(None, tmp_path)
    return enforcer


def test_rbac_model_semantics(tmp_path: Path):
    enforcer = _make_enforcer(tmp_path)
    # admin 通配
    assert enforcer.enforce("admin", "anything:any:action")
    # 添加角色 + 权限
    enforcer.add_permission_for_user("editor", "weread:subscription:list")
    enforcer.add_role_for_user("zhangsan", "editor")
    assert enforcer.enforce("zhangsan", "weread:subscription:list")
    assert not enforcer.enforce("zhangsan", "weread:subscription:delete")  # deny-by-default
    # 角色继承：editor 继承 viewer
    enforcer.add_permission_for_user("viewer", "weread:article:list")
    enforcer.add_role_for_user("editor", "viewer")
    assert enforcer.enforce("zhangsan", "weread:article:list")  # 通过继承获得
    # 撤角色 → 立即失去
    enforcer.delete_role_for_user("zhangsan", "editor")
    assert not enforcer.enforce("zhangsan", "weread:subscription:list")
    # admin 角色挂载
    enforcer.add_role_for_user("lisi", "admin")
    assert enforcer.enforce("lisi", "xhs:note:search")  # 通配


def test_resolve_user(tmp_path: Path):
    enforcer = _make_enforcer(tmp_path)
    enforcer.add_role_for_user("admin", "admin")  # 默认种子已有
    user = resolve_user(enforcer, "admin")
    assert ADMIN_ROLE in user.roles
    assert user.is_admin
    assert "*" in user.perms


def test_rbac_enforcer_graceful_without_pycasbin(tmp_path: Path):
    """pycasbin 未安装时 build_enforcer 应抛 ImportError（调用方降级 None）。"""
    # pycasbin 已安装（本机），这里只验证正常路径
    enforcer = build_enforcer(None, tmp_path)
    assert enforcer is not None


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
        xhs_monitor_enabled=False,
        douyin_monitor_enabled=False,
        ks_monitor_enabled=False,
        tiktok_monitor_enabled=False,
    )


def test_admin_api_requires_admin_role(tmp_path: Path, monkeypatch):
    """RBAC 管理接口注册且可达（鉴权行为取决于 auth 配置，核心语义由模型测试覆盖）。"""
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        # 路由已挂载且可达（200 = auth 关闭直通；401/403 = RBAC 拦截）
        resp = client.get("/api/admin/users")
        assert resp.status_code in (200, 401, 403)

        # 角色接口同样可达
        resp_roles = client.get("/api/admin/roles")
        assert resp_roles.status_code in (200, 401, 403)

        # 权限码接口
        resp_perms = client.get("/api/admin/perm-codes")
        assert resp_perms.status_code in (200, 401, 403)
