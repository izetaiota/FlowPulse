"""通用链接下载测试：抽链、来源识别、任务执行（mock yt-dlp）、API 流程、媒体库与穿越防护。"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.downloader import service as svc
from flowpulse.modules.downloader.service import (
    DownloadService,
    DownloadStore,
    extract_urls,
    source_hint,
)


def test_extract_urls_from_share_text():
    text = "【抖音】好物分享 https://v.douyin.com/AbCd123/ 复制此链接，第二个 https://b23.tv/xyz99 ，重复 https://v.douyin.com/AbCd123/"
    urls = extract_urls(text)
    assert urls == ["https://v.douyin.com/AbCd123/", "https://b23.tv/xyz99"]
    assert extract_urls("没有链接的文案") == []


def test_source_hint():
    assert source_hint("https://v.douyin.com/x/") == "douyin"
    assert source_hint("https://www.bilibili.com/video/BV1x") == "bilibili"
    assert source_hint("https://www.xiaohongshu.com/explore/1") == "xhs"
    assert source_hint("https://example.com/a") == "other"


def test_store_crud(tmp_path: Path):
    store = DownloadStore(tmp_path / "downloads")
    task = store.create("https://example.com/x")
    assert store.get(task.id).url == "https://example.com/x"
    assert len(store.list()) == 1
    # 产物文件随任务目录删除
    (store.task_dir(task.id) / "video.mp4").write_bytes(b"x" * 10)
    assert store.delete(task.id) is True
    assert store.get(task.id) is None
    assert not store.task_dir(task.id).exists()
    assert store.delete(task.id) is False


def _fake_run_sync_ok(self, task_id: str) -> None:
    task = self.store.get(task_id)
    task_dir = self.store.task_dir(task_id)
    media = task_dir / f"{task_id}.mp4"
    media.write_bytes(b"0" * 1024)
    task.status = "completed"
    task.progress = 100
    task.title = "演示视频"
    task.filename = media.name
    task.file_size = 1024
    task.message = "完成"
    self.store.save(task)


@pytest.mark.asyncio
async def test_submit_creates_and_runs_tasks(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(svc, "yt_dlp_available", lambda: True)
    monkeypatch.setattr(DownloadService, "_run_sync", _fake_run_sync_ok)

    service = DownloadService(DownloadStore(tmp_path / "downloads"))
    tasks = service.submit_text("https://v.douyin.com/a/ 和 https://b23.tv/b/")
    assert len(tasks) == 2
    await asyncio.gather(*service._running)  # 等后台任务完成
    statuses = {t.url: t.status for t in service.store.list()}
    assert set(statuses.values()) == {"completed"}


@pytest.mark.asyncio
async def test_submit_without_ytdlp_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(svc, "yt_dlp_available", lambda: False)
    service = DownloadService(DownloadStore(tmp_path / "downloads"))
    with pytest.raises(RuntimeError, match="yt-dlp"):
        service.submit_text("https://v.douyin.com/a/")
    with pytest.raises(ValueError):
        monkeypatch.setattr(svc, "yt_dlp_available", lambda: True)
        service.submit_text("没有链接")


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
        xhs_monitor_enabled=False,
    )


def test_downloads_api_and_media_browser(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    monkeypatch.setattr(svc, "yt_dlp_available", lambda: True)
    monkeypatch.setattr(DownloadService, "_run_sync", _fake_run_sync_ok)

    with TestClient(create_app()) as client:
        # 未安装依赖时优雅 400（关掉 mock 再开）
        monkeypatch.setattr(svc, "yt_dlp_available", lambda: False)
        resp = client.post("/api/v1/downloads", json={"text": "https://v.douyin.com/a/"})
        assert resp.status_code == 400 and "yt-dlp" in resp.json()["detail"]

        monkeypatch.setattr(svc, "yt_dlp_available", lambda: True)
        created = client.post(
            "/api/v1/downloads", json={"text": "看看这个 https://v.douyin.com/a/"}
        )
        assert created.status_code == 202
        task_id = created.json()["tasks"][0]["id"]

        # 轮询等待后台下载完成（TestClient 每次请求推进事件循环）
        import time

        for _ in range(40):
            task = client.get(f"/api/v1/downloads/{task_id}").json()
            if task["status"] == "completed":
                break
            time.sleep(0.05)
        assert task["status"] == "completed"

        # 媒体库：任务目录可见、task.json 不外泄
        listing = client.get("/api/v1/downloads/files/list", params={"root": "downloads"}).json()
        names = [e["name"] for e in listing["entries"]]
        assert task_id in names and "task.json" not in names

        detail = client.get(
            "/api/v1/downloads/files/list", params={"root": "downloads", "path": task_id}
        ).json()
        media = [e for e in detail["entries"] if e["name"].endswith(".mp4")]
        assert len(media) == 1 and media[0]["previewable"] is True

        # 文件内容可取、穿越路径被拒
        file_resp = client.get(
            "/api/v1/downloads/files/content",
            params={"root": "downloads", "path": f"{task_id}/{media[0]['name']}"},
        )
        assert file_resp.status_code == 200 and len(file_resp.content) == 1024
        evil = client.get(
            "/api/v1/downloads/files/content",
            params={"root": "downloads", "path": "../../"},
        )
        assert evil.status_code == 400
        assert client.get("/api/v1/downloads/files/list", params={"root": "nope"}).status_code == 400

        # 删除任务 → 目录级联消失
        assert client.delete(f"/api/v1/downloads/{task_id}").json()["deleted"] is True
        listing = client.get("/api/v1/downloads/files/list", params={"root": "downloads"}).json()
        assert task_id not in [e["name"] for e in listing["entries"]]
