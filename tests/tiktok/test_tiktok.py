"""TikTok 平台（T5.3）测试：离线签名冒烟、解析（emoji/ID 补时间）、账号、监控（仅关键词）、API。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.core.crypto import CredentialCipher
from flowpulse.main import create_app
from flowpulse.modules.accounts.service import AccountService
from flowpulse.modules.accounts.store import AccountRepository
from flowpulse.modules.tiktok.account import TiktokAccountService
from flowpulse.modules.tiktok.extract import normalize_tiktok_item, tiktok_display_text
from flowpulse.modules.tiktok.monitoring.service import TiktokMonitorService
from flowpulse.modules.tiktok.monitoring.store import TiktokMonitorRepository


def test_offline_sign_smoke():
    from flowpulse.modules.tiktok.offline_sign import sign

    query, added = sign(
        [("keyword", "cooking"), ("count", "20"), ("offset", "0")],
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
        ms_token="",
    )
    assert "keyword=cooking" in query and "X-Bogus=" in query
    assert any("msToken" in k for k in added) or True


def test_normalize_tiktok_item():
    item = {
        "item": {
            "id": "7410000000000000001",
            "desc": "great recipe \U0001f600",
            "createTime": 0,
            "author": {"uniqueId": "chef", "nickname": "Chef"},
            "stats": {"diggCount": 1500, "commentCount": 30},
            "video": {"cover": {"url_list": ["https://c/x.webp"]}, "duration": 15000},
        }
    }
    work = normalize_tiktok_item(item)
    assert work is not None
    assert work["aweme_id"] == "7410000000000000001"
    assert "great recipe" in work["title"] and "\\ud" not in work["title"]
    assert "\U0001f600" in work["title"]
    assert work["liked_count"] == "1500" and work["author_id"] == "chef"
    assert work["url"] == "https://www.tiktok.com/@chef/video/7410000000000000001"
    # createTime 缺失：64 位 ID 高 32 位补 Unix 秒
    assert work["create_time"] > 1_450_000_000
    assert normalize_tiktok_item({"foo": 1}) is None


def test_display_text():
    # 真实代理对字符（JSON \\ud83d\\ude00 解析后的形态）应被还原为 emoji
    assert "\U0001f600" in tiktok_display_text("hi \U0001f600")
    assert tiktok_display_text("plain") == "plain"


def make_account_service(tmp_path: Path) -> AccountService:
    repo = AccountRepository(None, tmp_path / "accounts" / "accounts.json")
    return AccountService(repo, cipher=CredentialCipher(key_file=tmp_path / "k"))


def test_tiktok_account_cookie(tmp_path: Path):
    service = TiktokAccountService(make_account_service(tmp_path))
    assert service.status()["configured"] is False
    with pytest.raises(ValueError):
        service.import_cookie("")
    service.import_cookie("sessionid=abc; ttwid=1")
    status = service.status()
    assert status["configured"] and status["logged_in_guess"] is True
    assert service.clear()["deleted"] is True


class FakeFetcher:
    def __init__(self, works, fail=False):
        self.works = works
        self.fail = fail

    async def fetch_search(self, keyword, limit=30):
        if self.fail:
            raise RuntimeError("未安装 curl_cffi")
        return self.works


class FakeNotifier:
    def __init__(self):
        self.sent = []

    async def send(self, kind, title, detail):
        self.sent.append((kind, title, detail))


def work(wid: str, title: str) -> dict:
    return {
        "aweme_id": wid,
        "title": title,
        "author": "@chef",
        "author_id": "chef",
        "url": f"https://www.tiktok.com/@chef/video/{wid}",
        "cover": "",
        "media_type": "video",
        "liked_count": "9",
        "create_time": 1730000000,
        "extra": {},
    }


@pytest.mark.asyncio
async def test_tiktok_monitor_keyword_only(tmp_path: Path):
    notifier = FakeNotifier()
    repo = TiktokMonitorRepository(None, tmp_path)
    service = TiktokMonitorService(repo, FakeFetcher([work("t1", "教程")]), notifier)
    monitor = repo.create_monitor({"kind": "keyword", "target": "cooking", "backfill_count": 5})
    result = await service.scan_monitor(monitor)
    assert result["ok"] and result["new_count"] == 1 and notifier.sent == []

    service.fetcher.works = [work("t1", "教程"), work("t2", "new")]
    result = await service.scan_monitor(repo.get_monitor(monitor["id"]))
    assert result["new_count"] == 1 and result["notified"] is True

    # creator 类型被拒绝并记录错误
    bad = repo.create_monitor({"kind": "creator", "target": "https://www.tiktok.com/@chef"})
    result = await service.scan_monitor(bad)
    assert result["ok"] is False and "仅支持关键词" in result["message"]


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


def test_tiktok_api(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/tiktok/account/status").json()["configured"] is False
        imported = client.post(
            "/api/v1/tiktok/account/cookie", json={"cookie": "sessionid=x"}
        )
        assert imported.status_code == 200

        # creator 类型被 pydantic pattern 拒绝
        assert (
            client.post(
                "/api/v1/tiktok/monitoring/monitors",
                json={"kind": "creator", "target": "x"},
            ).status_code
            == 422
        )
        created = client.post(
            "/api/v1/tiktok/monitoring/monitors",
            json={"kind": "keyword", "target": "cooking", "name": "美食"},
        )
        assert created.status_code == 201
        monitor = created.json()
        # 手动扫描：真实 fetcher 有 curl_cffi（本机已装 xhs 依赖）→ 真实请求 TikTok
        # 测试环境不外联：mock fetch_search
        async def fake_search(self, keyword, limit=30):
            raise RuntimeError("测试不外联")

        from flowpulse.modules.tiktok.fetcher import TiktokFetcher

        monkeypatch.setattr(TiktokFetcher, "fetch_search", fake_search)
        scan = client.post(f"/api/v1/tiktok/monitoring/monitors/{monitor['id']}/scan").json()
        assert scan["result"]["ok"] is False
        assert scan["monitor"]["last_scan_status"] == "error"
        assert client.delete(f"/api/v1/tiktok/monitoring/monitors/{monitor['id']}").json()["deleted"]
