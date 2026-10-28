"""扫码登录测试：会话管理器辅助函数 + API 端点（fake 管理器注入）。"""

from pathlib import Path

from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.weread.api import get_weread_qr_login
from flowpulse.modules.weread.qrlogin import _cookie_string, _has_login_cookie


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_request_interval_seconds=0,
        weread_sync_interval_minutes=0,
        weread_webhook_url="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_login_cookie_detection():
    assert _has_login_cookie(
        [{"name": "wr_vid", "value": "1"}, {"name": "wr_skey", "value": "x"}]
    )
    assert not _has_login_cookie([{"name": "wr_vid", "value": "1"}])
    assert not _has_login_cookie([])


def test_cookie_string_joins_and_skips_empty():
    pairs = [
        {"name": "wr_vid", "value": "123"},
        {"name": "wr_skey", "value": "abc"},
        {"name": "empty", "value": ""},
    ]
    assert _cookie_string(pairs) == "wr_vid=123; wr_skey=abc"


def test_qr_status_idle_without_launch(tmp_path: Path, monkeypatch):
    """刚起服务时状态应为 idle，且不能触发浏览器启动。"""
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: make_settings(tmp_path))
    with TestClient(create_app()) as client:
        body = client.get("/api/weread/credential/qr-login").json()
        assert body["state"] == "idle"


class FakeQrManager:
    def __init__(self):
        self.state = "idle"

    def status(self) -> dict:
        return {
            "state": self.state,
            "message": "浏览器窗口已打开，请用微信扫码授权",
            "page_url": "https://weread.qq.com/#login",
            "started_at": "2026-10-28T00:00:00+00:00",
        }

    async def start(self) -> dict:
        self.state = "pending"
        return self.status()

    async def cancel(self) -> dict:
        self.state = "cancelled"
        return self.status()


def test_qr_login_api_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: make_settings(tmp_path))
    app = create_app()
    fake = FakeQrManager()
    app.dependency_overrides[get_weread_qr_login] = lambda: fake

    with TestClient(app) as client:
        assert client.post("/api/weread/credential/qr-login").json()["state"] == "pending"
        assert client.get("/api/weread/credential/qr-login").json()["state"] == "pending"
        assert client.delete("/api/weread/credential/qr-login").json()["state"] == "cancelled"
