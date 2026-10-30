"""快手平台（T5.1）测试：解析（REST/GraphQL 双形态）、Cookie 助手、监控扫描、API。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.core.crypto import CredentialCipher
from flowpulse.main import create_app
from flowpulse.modules.accounts.service import AccountService
from flowpulse.modules.accounts.store import AccountRepository
from flowpulse.modules.ks.account import KsAccountService
from flowpulse.modules.ks.browser import (
    KsBrowserFetcher,
    has_ks_login_cookie,
    ks_cookie_storage_state,
    user_id_from,
)
from flowpulse.modules.ks.extract import (
    _dig_rest_feeds,
    _search_feeds,
    normalize_ks_feed,
)
from flowpulse.modules.ks.monitoring.service import KsMonitorService
from flowpulse.modules.ks.monitoring.store import KsMonitorRepository

VALID_COOKIE = "userId=123; passToken=abc; kuaishou.server.web_st=x"


# ---- 解析 ----


def test_normalize_ks_feed_rest_and_graphql():
    feed = {
        "photo": {
            "id": "px1",
            "caption": "收纳教程",
            "timestamp": 1730000000000,  # 毫秒
            "coverUrl": "https://p/c.webp",
            "photoUrl": "https://v/x.mp4",
            "realLikeCount": "1.2万",
            "commentCount": 3,
            "duration": 15000,
        },
        "author": {"userId": "u1", "name": "小明"},
    }
    work = normalize_ks_feed(feed)
    assert work is not None
    assert work["photo_id"] == "px1" and work["title"] == "收纳教程"
    assert work["liked_count"] == "12000"  # '1.2万' → 12000
    assert work["create_time"] == 1730000000
    assert work["url"] == "https://www.kuaishou.com/short-video/px1"
    assert normalize_ks_feed({"photo": {}}) is None
    assert normalize_ks_feed("junk") is None


def test_dig_rest_and_search_feeds():
    rest = {"feeds": [{"photo": {"id": "a"}}]}
    assert len(_dig_rest_feeds(rest)) == 1
    graphql = {"data": {"visionSearchPhoto": {"feeds": [{"photo": {"id": "b"}}]}}}
    assert len(_search_feeds(graphql)) == 1
    nested_rest = {"data": {"photos": [{"photo": {"id": "c"}}]}}
    assert len(_search_feeds(nested_rest)) == 1


def test_helpers():
    assert user_id_from("https://www.kuaishou.com/profile/3xabc") == "3xabc"
    assert user_id_from("3xraw") == "3xraw"
    assert has_ks_login_cookie(VALID_COOKIE) is True
    assert has_ks_login_cookie("userId=1") is False
    state = ks_cookie_storage_state(VALID_COOKIE)
    assert state is not None and all(c["domain"] == ".kuaishou.com" for c in state["cookies"])


# ---- 账号 ----


def make_account_service(tmp_path: Path) -> AccountService:
    repo = AccountRepository(None, tmp_path / "accounts" / "accounts.json")
    return AccountService(repo, cipher=CredentialCipher(key_file=tmp_path / "accounts" / ".k"))


def test_ks_account_cookie_import(tmp_path: Path):
    service = KsAccountService(make_account_service(tmp_path), tmp_path / "profiles")
    with pytest.raises(ValueError):
        service.import_cookie("userId=only")
    result = service.import_cookie(VALID_COOKIE)
    assert result["configured"] is True
    status = service.status()
    assert status["configured"] and status["logged_in_guess"] is True
    account = service.account_service.repository.find_by_key("kuaishou", "default")
    assert account is not None
    assert service.account_service.get_credential(account["id"]) == VALID_COOKIE
    assert service.clear()["deleted"] is True


# ---- 监控（FakeFetcher） ----


class FakeFetcher:
    def __init__(self, works, fail=False):
        self.works = works
        self.fail = fail

    async def fetch_user_works(self, target, limit=30):
        if self.fail:
            raise RuntimeError("浏览器引擎未安装")
        return self.works

    async def fetch_search(self, keyword, limit=30):
        if self.fail:
            raise RuntimeError("浏览器引擎未安装")
        return self.works


class FakeNotifier:
    def __init__(self):
        self.sent = []

    async def send(self, kind, title, detail):
        self.sent.append((kind, title, detail))


def work(pid: str, title: str) -> dict:
    return {
        "photo_id": pid,
        "title": title,
        "author": "作者",
        "author_id": "u1",
        "url": f"https://www.kuaishou.com/short-video/{pid}",
        "cover": "",
        "media_type": "video",
        "liked_count": "9",
        "create_time": 1730000000,
        "extra": {},
    }


@pytest.mark.asyncio
async def test_ks_scan_baseline_and_increment(tmp_path: Path):
    notifier = FakeNotifier()
    repo = KsMonitorRepository(None, tmp_path)
    service = KsMonitorService(repo, FakeFetcher([work("p1", "教程一")]), notifier)
    monitor = repo.create_monitor({"kind": "keyword", "target": "收纳", "backfill_count": 5})

    result = await service.scan_monitor(monitor)
    assert result["ok"] and result["new_count"] == 1 and notifier.sent == []

    service.fetcher.works = [work("p1", "教程一"), work("p2", "新教程")]
    result = await service.scan_monitor(repo.get_monitor(monitor["id"]))
    assert result["new_count"] == 1 and result["notified"] is True
    assert "新教程" in notifier.sent[0][2]


@pytest.mark.asyncio
async def test_ks_scan_error_recorded(tmp_path: Path):
    repo = KsMonitorRepository(None, tmp_path)
    service = KsMonitorService(repo, FakeFetcher([], fail=True))
    monitor = repo.create_monitor({"kind": "creator", "target": "https://www.kuaishou.com/profile/3x"})
    result = await service.scan_monitor(monitor)
    assert result["ok"] is False
    assert repo.get_monitor(monitor["id"])["last_scan_status"] == "error"


# ---- API ----


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
    )


def test_ks_api_flow(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/ks/account/status").json()["configured"] is False
        assert client.post("/api/v1/ks/account/cookie", json={"cookie": "bad"}).status_code == 400
        imported = client.post("/api/v1/ks/account/cookie", json={"cookie": VALID_COOKIE})
        assert imported.status_code == 200
        accounts = client.get("/api/v1/accounts", params={"platform": "kuaishou"}).json()["accounts"]
        assert len(accounts) == 1

        created = client.post(
            "/api/v1/ks/monitoring/monitors",
            json={"kind": "keyword", "target": "好物", "name": "快手好物监控"},
        )
        assert created.status_code == 201
        monitor = created.json()
        scan = client.post(f"/api/v1/ks/monitoring/monitors/{monitor['id']}/scan").json()
        assert scan["result"]["ok"] is False  # 真实 fetcher 无浏览器引擎/无数据，优雅失败
        assert scan["monitor"]["last_scan_status"] == "error"
        assert client.delete(f"/api/v1/ks/monitoring/monitors/{monitor['id']}").json()["deleted"]
