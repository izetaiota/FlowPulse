"""Web 登录鉴权测试：关闭态直通、登录发 Token、受保护接口、查询参数兼容。"""

from pathlib import Path

from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app

BOOK_ID = "MP_WXS_3012726261"


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_request_interval_seconds=0,
        weread_sync_interval_minutes=0,
        weread_webhook_url="",
        weread_cookie_refresh_hours=0,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_auth_disabled_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: make_settings(tmp_path))
    with TestClient(create_app()) as client:
        assert client.get("/api/auth/session").json()["enabled"] is False
        # 未配置密码：业务接口直通（与历史行为一致）
        assert client.get("/api/weread/status").status_code == 200


def test_login_and_protected_endpoints(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "flowpulse.main.get_settings",
        lambda: make_settings(tmp_path, admin_username="admin", admin_password="s3cret"),
    )
    with TestClient(create_app()) as client:
        # 未登录 → 401
        assert client.get("/api/weread/status").status_code == 401

        # 错误密码 → 401；正确 → 拿到 token
        assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
        login = client.post("/api/auth/login", json={"username": "admin", "password": "s3cret"}).json()
        assert login["token"] and login["username"] == "admin"

        # Bearer Token 放行；session 能识别当前用户
        headers = {"Authorization": f"Bearer {login['token']}"}
        assert client.get("/api/weread/status", headers=headers).status_code == 200
        assert client.get("/api/auth/session", headers=headers).json()["username"] == "admin"

        # RSS 等无法带 Header 的客户端：?token= 查询参数同样放行
        assert client.get(f"/api/weread/rss/all.xml?token={login['token']}").status_code == 200

        # 健康检查不锁（容器探活）
        assert client.get("/health/live").status_code == 200

        # 假 token → 401
        assert client.get(
            "/api/weread/status", headers={"Authorization": "Bearer fake.sig.sig"}
        ).status_code == 401


def test_token_expiry(tmp_path: Path, monkeypatch):
    from flowpulse.core.auth import create_token, init_auth, verify_token

    init_auth("admin", "pw", tmp_path)
    token, _ = create_token("admin", ttl_seconds=-1)  # 已过期
    assert verify_token(token) is None
    token, _ = create_token("admin", ttl_seconds=60)
    assert verify_token(token) == "admin"
    assert verify_token("tampered." + token.split(".", 2)[2]) is None
