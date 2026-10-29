"""XHS 运维闭环测试：Cookie 静态加密、凭证定时校验与掉线告警。"""

import asyncio
import json
from pathlib import Path

from flowpulse.modules.xhs.integration.credential_check import XhsCredentialChecker
from flowpulse.modules.xhs.integration.store import CookieStore


class FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, key: str, title: str, message: str, cooldown_seconds: int = 3600) -> bool:
        self.sent.append(key)
        return True


class FakeXhsService:
    def __init__(self, statuses: dict):
        self._statuses = statuses  # platform -> LoginStatus-like

    async def login_status(self, platform: str):
        class S:
            pass

        s = S()
        item = self._statuses[platform]
        s.logged_in = item.get("logged_in", False)
        s.user_id = item.get("user_id")
        s.message = item.get("message", "")
        return s


# ---- CookieStore 加密 ----


def test_cookie_store_encrypted_at_rest(tmp_path: Path):
    store = CookieStore(tmp_path)
    store.set("pc", "a1=xxx; web_session=secret")

    raw = json.loads((tmp_path / "xhs" / "cookies.json").read_text(encoding="utf-8"))
    assert raw["pc"].startswith("gAAA")
    assert "web_session=secret" not in raw["pc"]

    assert store.get("pc") == "a1=xxx; web_session=secret"


def test_cookie_store_legacy_plaintext_readable(tmp_path: Path):
    target = tmp_path / "xhs" / "cookies.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"pc": "a1=plain"}), encoding="utf-8")

    store = CookieStore(tmp_path)
    assert store.get("pc") == "a1=plain"  # 旧明文兼容
    store.set("pc", "a1=plain")  # 保存自动升级为密文
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert raw["pc"].startswith("gAAA")


def test_cookie_store_wrong_key_unreadable(tmp_path: Path):
    from cryptography.fernet import Fernet

    CookieStore(tmp_path, credential_key=Fernet.generate_key().decode()).set("pc", "abc")
    broken = CookieStore(tmp_path, credential_key=Fernet.generate_key().decode())
    assert broken.get("pc") is None


# ---- 凭证校验调度 ----


def test_checker_alerts_on_logout(tmp_path: Path):
    async def run() -> None:
        notifier = FakeNotifier()
        service = FakeXhsService({"pc": {"logged_in": True}, "creator": {"logged_in": False}})
        checker = XhsCredentialChecker(service, tmp_path, notifier=notifier, interval_minutes=360)

        first = await checker.run_once()
        assert first["pc"]["logged_in"] is True
        assert notifier.sent == []  # 从未登录变为登录不告警

        # pc 掉线 → 告警；creator 保持未登录 → 不告警
        service._statuses["pc"]["logged_in"] = False
        second = await checker.run_once()
        assert second["pc"]["logged_in"] is False
        assert notifier.sent == ["xhs_credential"]

        # 持续掉线不重复告警（Webhook 侧还有冷却）
        third = await checker.run_once()
        assert third["pc"]["logged_in"] is False
        assert notifier.sent == ["xhs_credential"]

    asyncio.run(run())


def test_checker_state_and_catchup(tmp_path: Path):
    from datetime import datetime, timedelta, timezone

    checker = XhsCredentialChecker(FakeXhsService({}), tmp_path, interval_minutes=360)
    assert checker._seconds_until_due() == 360 * 60  # 从未跑过

    state = checker.status(populate=False)
    state["last_run_at"] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(timespec="seconds")
    from flowpulse.core.storage import atomic_write_json

    atomic_write_json(checker._state_path, state)
    assert checker._seconds_until_due() == 0  # 超期补跑
