"""T1.5 监控 RSS 测试：生成 XML、平台过滤、API 输出。"""

from pathlib import Path

from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.monitors_rss import build_monitor_rss


def test_build_monitor_rss():
    xml = build_monitor_rss(
        [
            {
                "title": "收纳教程", "url": "https://xhs/1", "note_id": "n1",
                "first_seen_at": "2026-10-30T10:00:00+00:00", "author": "小明",
                "liked_count": "9", "monitor_name": "收纳监控",
            },
            {
                "title": "", "aweme_id": "a1", "url": "https://dy/1",
                "first_seen_at": "2026-10-30T11:00:00+00:00", "author": "",
                "monitor_name": "", "liked_count": "0",
            },
        ],
        "测试 Feed",
    )
    assert xml.startswith("<?xml") and "<rss version=\"2.0\">" in xml
    assert "<title>收纳教程</title>" in xml
    assert "<title>a1</title>" in xml  # 空标题兜底到作品 ID
    assert "<guid isPermaLink=\"false\">n1</guid>" in xml
    assert "来源监控：收纳监控" in xml


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


def test_monitors_rss_api(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        # 空库：合法 XML，空 channel
        resp = client.get("/api/rss/monitors.xml")
        assert resp.status_code == 200
        assert "application/rss+xml" in resp.headers["content-type"]
        assert "全部平台" in resp.text and "<item>" not in resp.text

        # 注入 xhs 监控数据后：出现条目（直接 override 返回仓储元组）
        from flowpulse.modules.monitors_rss import get_rss_repositories
        from flowpulse.modules.xhs.monitoring.store import XhsMonitorRepository

        repo = XhsMonitorRepository(None, tmp_path)
        monitor = repo.create_monitor({"kind": "keyword", "target": "收纳", "name": "收纳监控"})
        repo.add_content(
            {"monitor_id": monitor["id"], "note_id": "n1", "title": "教程",
             "url": "https://xhs/1", "author": "小明", "liked_count": "9"}
        )
        client.app.dependency_overrides[get_rss_repositories] = lambda: (repo, None, None, None)

        resp = client.get("/api/rss/monitors.xml")
        assert "<title>教程</title>" in resp.text and "收纳监控" in resp.text

        # 平台过滤：douyin 无内容 → 空
        resp_dy = client.get("/api/rss/monitors.xml", params={"platform": "douyin"})
        assert "<item>" not in resp_dy.text
