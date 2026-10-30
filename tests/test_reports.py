"""报表中心测试：xlsx 生成与读回、API 导出与错误路径。"""

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.accounts.store import AccountRepository
from flowpulse.modules.douyin.monitoring.store import DouyinMonitorRepository
from flowpulse.modules.downloader.service import DownloadStore
from flowpulse.modules.reports import ReportsService
from flowpulse.modules.xhs.monitoring.store import XhsMonitorRepository

openpyxl = pytest.importorskip("openpyxl")


def make_service(tmp_path: Path) -> ReportsService:
    xhs = XhsMonitorRepository(None, tmp_path)
    douyin = DouyinMonitorRepository(None, tmp_path)
    downloads = DownloadStore(tmp_path / "downloads")
    accounts = AccountRepository(None, tmp_path / "accounts" / "accounts.json")

    monitor = xhs.create_monitor({"kind": "keyword", "target": "收纳", "name": "收纳监控"})
    xhs.add_content(
        {"monitor_id": monitor["id"], "note_id": "n1", "title": "收纳教程",
         "author": "小明", "liked_count": "9", "url": "https://xhs/1"}
    )
    douyin.create_monitor({"kind": "creator", "target": "https://www.douyin.com/user/MS4Wx"})
    accounts.create_managed("douyin", "default", "抖音账号")
    return ReportsService(xhs, douyin, downloads, accounts)


def test_build_all_kinds_roundtrip(tmp_path: Path):
    service = make_service(tmp_path)
    for kind in ("xhs-monitors", "xhs-contents", "douyin-monitors", "douyin-contents", "downloads", "accounts"):
        content, filename = service.build(kind)
        assert filename.startswith(f"flowpulse-{kind}-") and filename.endswith(".xlsx")
        sheet = openpyxl.load_workbook(BytesIO(content)).active
        rows = list(sheet.iter_rows(values_only=True))
        assert len(rows[0]) >= 8  # 表头
        if kind == "xhs-monitors":
            assert rows[1][1] == "关键词" and rows[1][2] == "收纳监控"
        if kind == "xhs-contents":
            assert rows[1][0] == "小红书" and rows[1][3] == "收纳教程"
        if kind == "accounts":
            assert rows[1][0] == "douyin" and rows[1][3] == "手动登记"
    with pytest.raises(KeyError):
        service.build("nope")


def test_reports_api(tmp_path: Path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
        xhs_monitor_enabled=False,
        douyin_monitor_enabled=False,
    )
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    # 注入测试数据：直接换掉 runtime 里的仓储依赖服务
    with TestClient(create_app()) as client:
        app = client.app
        service = make_service(tmp_path)
        from flowpulse.modules.reports import get_reports_service

        app.dependency_overrides[get_reports_service] = lambda: service

        catalog = client.get("/api/v1/reports").json()["reports"]
        assert len(catalog) == 8

        resp = client.get("/api/v1/reports/xhs-contents.xlsx")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "flowpulse-xhs-contents" in resp.headers["content-disposition"]
        assert len(resp.content) > 500

        assert client.get("/api/v1/reports/unknown.xlsx").status_code == 404
