"""抖音发布（T3.4）与签名库（T3.5）测试：mock 浏览器驱动，不打开真实浏览器。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.douyin.publish import driver, service as publish_service_module
from flowpulse.modules.douyin.publish.service import DouyinPublishService
from flowpulse.modules.douyin.publish.store import DouyinPublishStore


def make_service(tmp_path: Path, login=lambda: (None, None)) -> DouyinPublishService:
    store = DouyinPublishStore(None, tmp_path)
    return DouyinPublishService(store, tmp_path, login, tmp_path / "profiles", enabled=False)


def _media_file(tmp_path: Path) -> str:
    media = tmp_path / "downloads" / "t1"
    media.mkdir(parents=True, exist_ok=True)
    file = media / "a.mp4"
    file.write_bytes(b"0" * 16)
    return f"downloads/t1/{file.name}"


def test_publish_store_status_flow(tmp_path: Path):
    store = DouyinPublishStore(None, tmp_path)
    task = store.create({"title": "测试", "media_paths": ["downloads/t1/a.mp4"]})
    assert task["status"] == "draft"
    store.update(task["id"], {"status": "pending"})
    assert store.next_due("2099-01-01T00:00:00+00:00")["id"] == task["id"]
    # 定时未到不出队
    store.update(task["id"], {"scheduled_at": "2099-01-01T00:00:00+00:00"})
    assert store.next_due("2026-01-01T00:00:00+00:00") is None
    assert store.delete(task["id"]) is True


def test_media_path_guard(tmp_path: Path):
    service = make_service(tmp_path)
    rel = _media_file(tmp_path)
    assert service.resolve_media_paths([rel]) == [str((tmp_path / rel).resolve())]
    with pytest.raises(ValueError):
        service.resolve_media_paths(["../../etc/passwd"])
    # 媒体清单能列出刚创建的文件
    files = service.list_media_files()
    assert [f["path"] for f in files] == [rel]


@pytest.mark.asyncio
async def test_publish_process_without_account(tmp_path: Path):
    service = make_service(tmp_path)
    rel = _media_file(tmp_path)
    task = service.create_draft({"title": "无账号", "media_paths": [rel]})
    service.submit(task["id"])
    result = await service.process_next()
    assert result["status"] == "failed"
    assert "未配置抖音账号" in result["error"]


@pytest.mark.asyncio
async def test_publish_process_with_driver(tmp_path: Path, monkeypatch):
    service = make_service(tmp_path, login=lambda: ("sessionid=1; ttwid=2", {"cookies": []}))
    rel = _media_file(tmp_path)
    task = service.create_draft(
        {"title": "标题", "desc": "简介", "topics": "收纳,好物", "media_paths": [rel]}
    )
    service.submit(task["id"])

    calls: dict = {}

    async def fake_driver(storage_state, profile_dir, files, title, desc, **kwargs):
        calls.update(
            storage=storage_state, files=files, title=title, desc=desc, kwargs=kwargs
        )
        return True, "https://creator.douyin.com/content/manage", ""

    monkeypatch.setattr(driver, "publish_douyin_video", fake_driver)
    result = await service.process_next()
    assert result["status"] == "done" and result["result_url"].endswith("/content/manage")
    assert calls["title"] == "标题"
    assert "#收纳 #好物" in calls["desc"]  # 话题并入正文
    assert calls["files"][0].endswith("a.mp4")


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


def test_publish_api_flow(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    # worker 关闭（服务 enabled 由 lifespan 启动；TestClient 会启动——这里直接 mock process_next 空转）
    async def idle(self):
        return None

    monkeypatch.setattr(DouyinPublishService, "process_next", idle)
    rel = _media_file(tmp_path)
    with TestClient(create_app()) as client:
        media = client.get("/api/v1/douyin/publish/media-files").json()["files"]
        assert [f["path"] for f in media] == [rel]

        created = client.post(
            "/api/v1/douyin/publish",
            json={"title": "API 草稿", "desc": "内容", "media_paths": [rel]},
        )
        assert created.status_code == 201
        task = created.json()
        assert task["status"] == "draft"

        # 越界路径拒绝
        assert (
            client.post(
                "/api/v1/douyin/publish",
                json={"media_paths": ["../../x"]},
            ).status_code
            == 400
        )

        assert client.post(f"/api/v1/douyin/publish/{task['id']}/submit").json()["status"] == "pending"
        assert client.post(f"/api/v1/douyin/publish/{task['id']}/cancel").json()["status"] == "canceled"
        assert client.delete(f"/api/v1/douyin/publish/{task['id']}").json()["deleted"] is True


# ---- T3.5 签名库性质测试（无固定向量，验证结构性质） ----


def test_abogus_properties():
    from flowpulse.modules.douyin.signing.abogus import ABogus

    value = ABogus(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    ).get_value("sec_user_id=MS4Wabc&count=20", "")
    assert len(value) == 164 and value.isascii()
    # 同输入产出不同值（含随机成分）
    value2 = ABogus(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    ).get_value("sec_user_id=MS4Wabc&count=20", "")
    assert value != value2


def test_ms_token_and_impersonate():
    from flowpulse.modules.douyin.signing.mstoken import gen_false_ms_token
    from flowpulse.modules.douyin.signing.netfp import impersonate_for_ua

    token = gen_false_ms_token()
    assert len(token) == 126
    assert impersonate_for_ua("... Chrome/124.0 ...") == "chrome124"
    assert impersonate_for_ua("weird ua") == "chrome131"  # 无版本号回落默认目标
