import pytest
"""阶段 5 测试：Cookie 无头续期（refresher 编排逻辑与 API）。"""

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.weread.api import get_weread_cookie_refresher
from flowpulse.modules.weread.qrlogin import WereadQrLoginManager
from flowpulse.modules.weread.refresh import WereadCookieRefresher
from flowpulse.modules.weread.service import WereadService
from flowpulse.modules.weread.storage import WereadRepository

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


class FakeQrManager:
    def __init__(self, cookie: str = "", error: str | None = None):
        self.cookie = cookie
        self.error = error

    async def capture_cookie_headless(self) -> str:
        if self.error:
            raise RuntimeError(self.error)
        return self.cookie


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send(self, key: str, title: str, message: str, cooldown_seconds: int = 3600) -> bool:
        self.sent.append((key, title))
        return True


def build_refresher(tmp_path: Path, fake_manager, notifier=None):
    repository = WereadRepository(tmp_path)
    client = httpx.AsyncClient()
    service = WereadService(repository, client, request_interval_seconds=0)
    refresher = WereadCookieRefresher(
        fake_manager, service, repository, notifier=notifier, interval_hours=24
    )
    return refresher, repository, service


def test_refresh_profile_expired_marks_credential(tmp_path: Path):
    import asyncio

    repository = WereadRepository(tmp_path)
    repository.save_credential("old_cookie")
    notifier = FakeNotifier()
    refresher, repository, _ = build_refresher(tmp_path, FakeQrManager(cookie=""), notifier)

    result = asyncio.run(refresher.run_once())

    assert result["ok"] is False
    assert result["reason"] == "profile_expired"
    credential = repository.get_credential()
    assert credential.valid is False
    assert "重新扫码" in credential.last_error
    assert notifier.sent and notifier.sent[0][0] == "weread_cookie_refresh"
    # 状态已持久化
    state = repository.load_cookie_refresher_state()
    assert state["last_result"]["reason"] == "profile_expired"


def test_refresh_new_cookie_saved_and_changed(tmp_path: Path, monkeypatch):
    import asyncio

    refresher, repository, service = build_refresher(tmp_path, FakeQrManager(cookie="new_cookie"))
    repository.save_credential("old_cookie")

    async def fake_save(cookie: str) -> dict:
        repository.save_credential(cookie)
        return {"valid": True, "message": "Cookie 有效", "book_count": 3}

    monkeypatch.setattr(service, "save_credential", fake_save)
    result = asyncio.run(refresher.run_once())

    assert result["ok"] is True
    assert result["changed"] is True
    assert repository.get_credential().cookie == "new_cookie"


def test_refresh_same_cookie_not_changed(tmp_path: Path, monkeypatch):
    import asyncio

    refresher, repository, service = build_refresher(tmp_path, FakeQrManager(cookie="same"))
    repository.save_credential("same")

    async def fake_save(cookie: str) -> dict:
        return {"valid": True, "message": "Cookie 有效", "book_count": 3}

    monkeypatch.setattr(service, "save_credential", fake_save)
    result = asyncio.run(refresher.run_once())

    assert result["ok"] is True
    assert result["changed"] is False


def test_refresh_browser_busy(tmp_path: Path):
    import asyncio

    refresher, repository, _ = build_refresher(
        tmp_path, FakeQrManager(error="扫码登录窗口进行中，请等扫码结束再续期")
    )
    repository.save_credential("old_cookie")

    result = asyncio.run(refresher.run_once())

    assert result["ok"] is False
    assert result["reason"] == "browser_error"
    assert "扫码登录窗口进行中" in result["message"]
    # 凭证不受影响
    assert repository.get_credential().cookie == "old_cookie"


@pytest.mark.real_browser
def test_capture_headless_blocked_while_qr_running(tmp_path: Path):
    """扫码窗口开着时，无头续期应直接拒绝（同一 profile 不能双开）。"""
    import asyncio
    import types

    manager = WereadQrLoginManager(tmp_path / "profile", on_cookie=lambda _c: {})
    manager._task = types.SimpleNamespace(done=lambda: False)  # 模拟扫码任务进行中
    try:
        asyncio.run(manager.capture_cookie_headless())
        raise AssertionError("应当抛出 RuntimeError")
    except RuntimeError as exc:
        assert "扫码登录窗口进行中" in str(exc)


def test_refresh_api_endpoint(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: make_settings(tmp_path))
    app = create_app()

    class FakeRefresher:
        def status(self) -> dict:
            return {
                "enabled": True,
                "interval_hours": 24,
                "running": False,
                "last_run_at": "2026-10-28T00:00:00+00:00",
                "last_result": {"ok": True, "message": "Cookie 有效"},
                "task_alive": False,
            }

        async def run_once(self) -> dict:
            return {"ok": True, "reason": "", "message": "Cookie 有效", "changed": False}

    app.dependency_overrides[get_weread_cookie_refresher] = lambda: FakeRefresher()
    with TestClient(app) as client:
        body = client.post("/api/weread/credential/refresh").json()
        assert body["ok"] is True
        status = client.get("/api/weread/credential/refresh").json()
        assert status["enabled"] is True
        assert status["last_result"]["ok"] is True


def test_refresher_disabled_when_interval_zero(tmp_path: Path):
    import asyncio

    refresher, repository, _ = build_refresher(tmp_path, FakeQrManager(cookie="x"))
    refresher.interval_hours = 0
    refresher.start()
    state = repository.load_cookie_refresher_state()
    assert state["enabled"] is False
    assert refresher.status()["task_alive"] is False
    asyncio.run(refresher.stop())
