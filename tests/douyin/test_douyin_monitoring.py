"""抖音平台 P3-A 测试：规范化、账号（Cookie 导入/状态机）、监控扫描（FakeFetcher）、API。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.core.crypto import CredentialCipher
from flowpulse.main import create_app
from flowpulse.modules.accounts.service import AccountService
from flowpulse.modules.accounts.store import AccountRepository
from flowpulse.modules.browser.engine import cookie_string_to_parts, has_login_cookie
from flowpulse.modules.douyin.account import DouyinAccountService
from flowpulse.modules.douyin.browser import normalize_aweme, sec_uid_from
from flowpulse.modules.douyin.monitoring.service import DouyinMonitorService
from flowpulse.modules.douyin.monitoring.store import DouyinMonitorRepository

VALID_COOKIE = "ttwid=abc; sessionid=xyz; uid=1"


# ---- 规范化 ----


def test_normalize_aweme_video():
    work = normalize_aweme(
        {
            "aweme_id": "74123",
            "desc": "收纳教程",
            "author": {"nickname": "小明", "sec_uid": "MS4Wabc"},
            "video": {"play_addr": {"url_list": ["x"]}, "cover": {"url_list": ["c.webp"]}},
            "statistics": {"digg_count": 1234, "comment_count": 5},
            "create_time": 1730000000,
        }
    )
    assert work is not None
    assert work["aweme_id"] == "74123" and work["title"] == "收纳教程"
    assert work["author_id"] == "MS4Wabc" and work["media_type"] == "video"
    assert work["url"] == "https://www.douyin.com/video/74123"
    assert normalize_aweme({"desc": "无 id"}) is None


def test_sec_uid_from():
    assert sec_uid_from("https://www.douyin.com/user/MS4Wxyz?from=1") == "MS4Wxyz"
    assert sec_uid_from("MS4Wraw") == "MS4Wraw"


def test_cookie_helpers():
    parts = cookie_string_to_parts(VALID_COOKIE)
    assert {p["name"] for p in parts} == {"ttwid", "sessionid", "uid"}
    assert all(p["domain"] == ".douyin.com" for p in parts)
    assert has_login_cookie(VALID_COOKIE) is True
    assert has_login_cookie("ttwid=1") is False


# ---- 账号 ----


def make_account_service(tmp_path: Path) -> AccountService:
    repo = AccountRepository(None, tmp_path / "accounts" / "accounts.json")
    return AccountService(repo, cipher=CredentialCipher(key_file=tmp_path / "accounts" / ".k"))


def test_douyin_account_cookie_import(tmp_path: Path):
    service = DouyinAccountService(make_account_service(tmp_path), tmp_path / "profiles")

    # 不完整 Cookie 拒绝
    with pytest.raises(ValueError):
        service.import_cookie("sessionid=only")

    result = service.import_cookie(VALID_COOKIE)
    assert result["configured"] is True
    status = service.status()
    assert status["configured"] and status["logged_in_guess"] is True
    # 凭证加密落库
    account = service.account_service.repository.find_by_key("douyin", "default")
    assert service.account_service.get_credential(account["id"]) == VALID_COOKIE

    # 重复导入 = 更新（不报错）
    service.import_cookie("ttwid=2; sessionid=3")
    assert service.account_service.get_credential(account["id"]) == "ttwid=2; sessionid=3"

    # 清除
    assert service.clear()["deleted"] is True
    assert service.status()["configured"] is False


def test_qr_poll_unknown_session(tmp_path: Path):
    service = DouyinAccountService(make_account_service(tmp_path), tmp_path / "profiles")
    assert service.qr_poll("nope")["state"] == "unknown"


# ---- 监控（FakeFetcher，无真实浏览器） ----


class FakeFetcher:
    def __init__(self, works, fail: bool = False):
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


def work(wid: str, title: str) -> dict:
    return {
        "aweme_id": wid,
        "title": title,
        "author": "作者",
        "author_id": "MS4W1",
        "url": f"https://www.douyin.com/video/{wid}",
        "cover": "",
        "media_type": "video",
        "liked_count": "9",
        "create_time": 1730000000,
        "extra": {},
    }


def make_monitor_service(tmp_path: Path, works, notifier=None, fail=False):
    repo = DouyinMonitorRepository(None, tmp_path)
    service = DouyinMonitorService(repo, FakeFetcher(works, fail=fail), notifier=notifier)
    return repo, service


@pytest.mark.asyncio
async def test_douyin_scan_baseline_increment_notify(tmp_path: Path):
    notifier = FakeNotifier()
    repo, service = make_monitor_service(tmp_path, [work("a1", "教程一")], notifier)
    monitor = repo.create_monitor({"kind": "keyword", "target": "收纳", "backfill_count": 5})

    result = await service.scan_monitor(monitor)
    assert result["ok"] and result["new_count"] == 1 and notifier.sent == []  # 基线不推送

    service.fetcher.works = [work("a1", "教程一"), work("a2", "新教程")]
    result = await service.scan_monitor(repo.get_monitor(monitor["id"]))
    assert result["new_count"] == 1 and result["notified"] is True
    assert "新教程" in notifier.sent[0][2]
    # 再扫无新增
    notifier.sent.clear()
    result = await service.scan_monitor(repo.get_monitor(monitor["id"]))
    assert result["new_count"] == 0 and notifier.sent == []


@pytest.mark.asyncio
async def test_douyin_scan_error_recorded(tmp_path: Path):
    repo, service = make_monitor_service(tmp_path, [], fail=True)
    monitor = repo.create_monitor({"kind": "creator", "target": "https://www.douyin.com/user/MS4Wx"})
    result = await service.scan_monitor(monitor)
    assert result["ok"] is False and "浏览器引擎未安装" in result["message"]
    assert repo.get_monitor(monitor["id"])["last_scan_status"] == "error"


def test_douyin_store_sqlite_mode(tmp_path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from flowpulse.db.engine import ensure_tables

    engine = create_engine(f"sqlite:///{tmp_path}/db.sqlite", future=True)
    ensure_tables(engine)
    repo = DouyinMonitorRepository(sessionmaker(engine, future=True), tmp_path)
    monitor = repo.create_monitor({"kind": "keyword", "target": "美食"})
    repo.add_content({"monitor_id": monitor["id"], "aweme_id": "w1", "title": "t"})
    assert repo.aweme_exists("w1")
    contents, total = repo.list_contents()
    assert total == 1 and contents[0]["aweme_id"] == "w1"
    assert repo.delete_monitor(monitor["id"]) is True


# ---- API 流程 ----


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
        xhs_monitor_enabled=False,
        douyin_monitor_enabled=False,
    )


def test_douyin_api_flow(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        # 账号：未配置 / 非法 Cookie / 合法导入
        assert client.get("/api/v1/douyin/account/status").json()["configured"] is False
        assert (
            client.post("/api/v1/douyin/account/cookie", json={"cookie": "bad"}).status_code == 400
        )
        imported = client.post("/api/v1/douyin/account/cookie", json={"cookie": VALID_COOKIE})
        assert imported.status_code == 200
        assert client.get("/api/v1/douyin/account/status").json()["logged_in_guess"] is True
        # 统一账号中心出现抖音行
        accounts = client.get("/api/v1/accounts", params={"platform": "douyin"}).json()["accounts"]
        assert len(accounts) == 1 and accounts[0]["kind"] == "managed"

        # 监控：创建 / 扫描（真实 fetcher 会因无浏览器引擎失败，优雅记录）/ 暂停 / 删除
        created = client.post(
            "/api/v1/douyin/monitoring/monitors",
            json={"kind": "keyword", "target": "收纳", "name": "抖音收纳监控"},
        )
        assert created.status_code == 201
        monitor = created.json()
        assert (
            client.post(
                "/api/v1/douyin/monitoring/monitors",
                json={"kind": "creator", "target": "短文本"},
            ).status_code
            == 400
        )
        scan = client.post(f"/api/v1/douyin/monitoring/monitors/{monitor['id']}/scan").json()
        assert scan["result"]["ok"] is False
        assert scan["monitor"]["last_scan_status"] == "error"
        patched = client.patch(
            f"/api/v1/douyin/monitoring/monitors/{monitor['id']}", json={"status": "paused"}
        ).json()
        assert patched["status"] == "paused"
        assert (
            client.delete(f"/api/v1/douyin/monitoring/monitors/{monitor['id']}").json()["deleted"]
            is True
        )
