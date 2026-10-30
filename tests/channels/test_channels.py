"""视频号平台（T5.2）测试：解析（auth/post 响应）、快照存储、服务 refresh（mock fetcher）、API。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.core.crypto import CredentialCipher
from flowpulse.main import create_app
from flowpulse.modules.accounts.service import AccountService
from flowpulse.modules.accounts.store import AccountRepository
from flowpulse.modules.channels.extract import dig_posts, parse_post, parse_profile
from flowpulse.modules.channels.service import ChannelsService, ChannelsStore


def test_parse_profile_and_post():
    profile = parse_profile(
        {"data": {"finderUser": {"nickname": "我的视频号", "username": "vlog_xyz", "headUrl": "https://h/x"}}}
    )
    assert profile["nickname"] == "我的视频号" and profile["username"] == "vlog_xyz"
    assert parse_profile({"data": {}}) == {}

    post = parse_post(
        {
            "objectId": "obj1",
            "objectDesc": {
                "description": "第一条视频",
                "mediaType": 1,
                "media": [{"coverUrl": "https://c/x", "url": ""}],  # 加密无明文
            },
            "createtime": 1730000000,
            "likeCount": "12",
            "commentCount": 3,
        }
    )
    assert post is not None
    assert post["object_id"] == "obj1" and post["title"] == "第一条视频"
    assert post["liked_count"] == "12" and post["media_type"] == "video"
    assert post["media_note"] == "加密 CDN，仅记录元数据"

    # 图文（mediaType 2）
    image_post = parse_post({"objectId": "o2", "objectDesc": {"mediaType": 2, "media": []}})
    assert image_post["media_type"] == "images"
    assert parse_post({"foo": 1}) is None
    assert dig_posts({"data": {"list": [{"objectId": "x"}]}}) == [{"objectId": "x"}]


def test_store_snapshot(tmp_path: Path):
    store = ChannelsStore(tmp_path)
    store.save_profile({"nickname": "测试号"})
    store.save_works([{"object_id": "a", "title": "t"}])
    assert store.get_profile()["nickname"] == "测试号"
    assert [w["object_id"] for w in store.list_works()] == ["a"]


@pytest.mark.asyncio
async def test_refresh_with_fake_fetcher(tmp_path: Path, monkeypatch):
    repo = AccountRepository(None, tmp_path / "accounts" / "accounts.json")
    accounts = AccountService(repo, cipher=CredentialCipher(key_file=tmp_path / "k"))
    store = ChannelsStore(tmp_path)
    service = ChannelsService(accounts, tmp_path / "profiles", store)

    class FakeFetcher:
        def __init__(self, login_state, root, headless=True):
            pass

        async def fetch_profile(self):
            return {"ok": True, "profile": {"nickname": "测试号", "username": "u1"}}

        async def fetch_works(self, limit=100):
            return {"ok": True, "works": [{"object_id": "w1", "title": "作品"}]}

    monkeypatch.setattr(
        "flowpulse.modules.channels.service.ChannelsBrowserFetcher", FakeFetcher
    )
    result = await service.refresh()
    assert result == {"ok": True, "nickname": "测试号", "works_count": 1}
    status = service.status()
    assert status["nickname"] == "测试号" and status["works_count"] == 1
    # 未登录账号（未扫码）——configured 仍为 False，但快照可用
    assert status["configured"] is False


def test_channels_api(tmp_path: Path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
        xhs_monitor_enabled=False,
        douyin_monitor_enabled=False,
        ks_monitor_enabled=False,
    )
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        status = client.get("/api/v1/channels/status").json()
        assert status["configured"] is False and status["works_count"] == 0
        assert client.get("/api/v1/channels/works").json()["works"] == []
        assert client.get("/api/v1/channels/profile").json()["profile"] is None
        # 未登录时刷新：真实 fetcher 会打开浏览器——mock 掉避免
        async def fake_refresh(self):
            return {"ok": False, "error": "视频号助手未登录", "logged_out": True}

        monkeypatch.setattr(ChannelsService, "refresh", fake_refresh)
        result = client.post("/api/v1/channels/refresh").json()
        assert result["ok"] is False and "未登录" in result["error"]
