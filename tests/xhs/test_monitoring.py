"""小红书作品监控测试：规范化、双模式存储、扫描基线/去重/过滤/通知、调度到期、API 流程。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.xhs.monitoring.scheduler import XhsMonitorScheduler
from flowpulse.modules.xhs.monitoring.service import (
    XhsMonitorService,
    normalize_note,
)
from flowpulse.modules.xhs.monitoring.store import XhsMonitorRepository

# ---- 两种返回形态的规范化 ----


def test_normalize_user_note_shape():
    note = normalize_note(
        {
            "note_id": "abc123",
            "display_title": "收纳好物",
            "type": "video",
            "user": {"user_id": "u1", "nickname": "小明"},
            "cover": {"url": "https://cdn/x.webp"},
            "interact_info": {"liked_count": "1.2万"},
            "xsec_token": "tok",
        }
    )
    assert note is not None
    assert note["note_id"] == "abc123" and note["title"] == "收纳好物"
    assert note["author"] == "小明" and note["liked_count"] == "1.2万"
    assert note["url"] == "https://www.xiaohongshu.com/explore/abc123?xsec_token=tok"


def test_normalize_search_item_shape():
    note = normalize_note(
        {
            "id": "n456",
            "model_type": "note",
            "note_card": {
                "display_title": "搜索结果",
                "type": "normal",
                "user": {"user_id": "u2", "nickname": "小红"},
                "interact_info": {"liked_count": 12},
            },
            "xsec_token": "tok2",
        }
    )
    assert note is not None
    assert note["note_id"] == "n456" and note["liked_count"] == "12"

    # 广告/非笔记项跳过
    assert normalize_note({"id": "ad1", "model_type": "hot_query"}) is None


# ---- 存储双模式 ----


def test_store_file_mode(tmp_path: Path):
    repo = XhsMonitorRepository(None, tmp_path)
    monitor = repo.create_monitor({"kind": "keyword", "target": "收纳", "name": "收纳监控"})
    assert monitor["status"] == "active" and monitor["last_scan_status"] == "never"

    assert repo.note_exists("n1") is False
    repo.add_content({"monitor_id": monitor["id"], "note_id": "n1", "title": "A", "notified": True})
    assert repo.note_exists("n1") is True

    repo.add_content({"monitor_id": monitor["id"], "note_id": "n2", "title": "B"})
    contents, total = repo.list_contents(monitor["id"], page=1, page_size=1)
    assert total == 2 and len(contents) == 1
    assert repo.content_stats() == {monitor["id"]: 2}

    # 删除目标级联清作品
    assert repo.delete_monitor(monitor["id"]) is True
    assert repo.list_contents() == ([], 0)


def test_store_sqlite_mode(tmp_path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from flowpulse.db.engine import ensure_tables

    engine = create_engine(f"sqlite:///{tmp_path}/db.sqlite", future=True)
    ensure_tables(engine)
    repo = XhsMonitorRepository(sessionmaker(engine, future=True), tmp_path)
    monitor = repo.create_monitor({"kind": "creator", "target": "https://www.xiaohongshu.com/user/profile/x"})
    repo.update_monitor(monitor["id"], {"last_scan_status": "ok"})
    assert repo.get_monitor(monitor["id"])["last_scan_status"] == "ok"
    repo.add_content({"monitor_id": monitor["id"], "note_id": "n1", "title": "A"})
    assert repo.note_exists("n1")
    contents, total = repo.list_contents()
    assert total == 1 and contents[0]["note_id"] == "n1"


# ---- 扫描服务 ----


class FakeXhsService:
    def __init__(self, notes, fail: bool = False):
        self.notes = notes
        self.fail = fail

    async def user_notes(self, url):
        return (not self.fail, "接口异常" if self.fail else "", self.notes)

    async def search(self, req):
        return (not self.fail, "接口异常" if self.fail else "", self.notes)


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, kind, title, detail):
        self.sent.append((kind, title, detail))


def note(note_id: str, title: str, nickname: str = "作者") -> dict:
    return {
        "note_id": note_id,
        "display_title": title,
        "type": "normal",
        "user": {"user_id": "u", "nickname": nickname},
        "cover": {},
        "interact_info": {"liked_count": "3"},
        "xsec_token": "t",
    }


def make_service(tmp_path: Path, notes, notifier=None, fail=False):
    repo = XhsMonitorRepository(None, tmp_path)
    service = XhsMonitorService(repo, FakeXhsService(notes, fail=fail), notifier=notifier)
    return repo, service


@pytest.mark.asyncio
async def test_first_scan_baseline_no_notify(tmp_path: Path):
    notifier = FakeNotifier()
    repo, service = make_service(tmp_path, [note(f"n{i}", f"标题{i}") for i in range(20)], notifier)
    monitor = repo.create_monitor(
        {"kind": "keyword", "target": "收纳", "backfill_count": 5}
    )
    result = await service.scan_monitor(monitor)
    assert result["ok"] and result["new_count"] == 5  # 基线截断
    assert notifier.sent == []  # 首扫不推送
    _, total = repo.list_contents()
    assert total == 5
    assert repo.get_monitor(monitor["id"])["last_scan_status"] == "ok"


@pytest.mark.asyncio
async def test_incremental_scan_dedupe_and_notify(tmp_path: Path):
    notifier = FakeNotifier()
    repo, service = make_service(tmp_path, [note("n1", "旧作")], notifier)
    monitor = repo.create_monitor({"kind": "keyword", "target": "收纳", "backfill_count": 10})
    await service.scan_monitor(monitor)  # 基线

    notifier.sent.clear()
    repo._monitors_path  # noqa: B018
    monitor = repo.get_monitor(monitor["id"])  # 带上 last_scan_at
    # 出现新作品
    repo_note = note("n2", "新作上线")
    service.xhs_service.notes = [note("n1", "旧作"), repo_note]
    result = await service.scan_monitor(monitor)
    assert result["new_count"] == 1 and result["notified"] is True
    assert len(notifier.sent) == 1 and "新作上线" in notifier.sent[0][2]
    # 再扫一次：无新作品，不重复推送
    notifier.sent.clear()
    result = await service.scan_monitor(repo.get_monitor(monitor["id"]))
    assert result["new_count"] == 0 and notifier.sent == []


@pytest.mark.asyncio
async def test_keyword_filters(tmp_path: Path):
    notifier = FakeNotifier()
    notes = [note("n1", "收纳教程"), note("n2", "美食探店"), note("n3", "收纳好物广告")]
    repo, service = make_service(tmp_path, notes, notifier)
    monitor = repo.create_monitor(
        {"kind": "keyword", "target": "x", "include_keywords": "收纳", "exclude_keywords": "广告"}
    )
    result = await service.scan_monitor(monitor)
    assert result["new_count"] == 1  # 只有 n1
    contents, _ = repo.list_contents()
    assert [c["note_id"] for c in contents] == ["n1"]


@pytest.mark.asyncio
async def test_scan_error_recorded(tmp_path: Path):
    repo, service = make_service(tmp_path, [], fail=True)
    monitor = repo.create_monitor({"kind": "keyword", "target": "x"})
    result = await service.scan_monitor(monitor)
    assert result["ok"] is False and "接口异常" in result["message"]
    assert repo.get_monitor(monitor["id"])["last_scan_status"] == "error"


# ---- 调度器到期判定 ----


def test_scheduler_due_logic(tmp_path: Path):
    repo = XhsMonitorRepository(None, tmp_path)
    scheduler = XhsMonitorScheduler(None, repo, tick_seconds=60)
    never = repo.create_monitor({"kind": "keyword", "target": "a"})
    repo.create_monitor({"kind": "keyword", "target": "paused", "status": "paused"})
    repo.create_monitor({"kind": "keyword", "target": "recent"})
    recent = repo.list_monitors()[-1]
    repo.update_monitor(
        recent["id"], {"last_scan_at": "2026-10-30T00:00:00+00:00", "last_scan_status": "ok"}
    )
    due = scheduler.due_monitors()
    ids = [m["id"] for m in due]
    assert never["id"] in ids  # 从未扫描 → 到期
    assert recent["id"] in ids  # 扫描时间久远 → 到期
    paused = [m for m in repo.list_monitors() if m["target"] == "paused"][0]
    assert paused["id"] not in ids  # 暂停不扫描


# ---- API 流程（真实 app，未登录小红书时扫描优雅降级为 error） ----


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
        xhs_monitor_enabled=False,  # 关掉后台调度，测试手动触发
    )


def test_monitoring_api_flow(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        # creator 目标必须是主页链接
        assert (
            client.post(
                "/api/v1/xhs/monitoring/monitors",
                json={"kind": "creator", "target": "not-a-url"},
            ).status_code
            == 400
        )
        created = client.post(
            "/api/v1/xhs/monitoring/monitors",
            json={"kind": "keyword", "target": "收纳", "name": "收纳监控", "interval_minutes": 60},
        )
        assert created.status_code == 201
        monitor = created.json()
        assert monitor["target"] == "收纳" and monitor["content_count"] == 0

        # 手动扫描：未登录小红书 → 优雅失败并记录
        scan = client.post(f"/api/v1/xhs/monitoring/monitors/{monitor['id']}/scan").json()
        assert scan["result"]["ok"] is False
        assert scan["monitor"]["last_scan_status"] == "error"

        # 暂停 / 删除
        patched = client.patch(
            f"/api/v1/xhs/monitoring/monitors/{monitor['id']}", json={"status": "paused"}
        ).json()
        assert patched["status"] == "paused"
        assert client.delete(f"/api/v1/xhs/monitoring/monitors/{monitor['id']}").json()["deleted"]
        assert client.get("/api/v1/xhs/monitoring/monitors").json()["monitors"] == []
