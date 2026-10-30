"""通知渠道模块测试：存储双模式、API 行为、渠道动态合并。"""

from pathlib import Path

import respx
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.notify import NotifyStore


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_request_interval_seconds=0,
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
        admin_password="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_notify_store_file_mode_roundtrip(tmp_path: Path):
    store = NotifyStore(None, tmp_path / "notify")
    assert store.list_channels() == []

    saved = store.replace_channels([
        {"name": "飞书群", "url": "https://open.feishu.cn/open-apis/bot/v2/hook/x", "enabled": True},
        {"url": "https://example.com/hook", "enabled": False},
    ])
    assert saved[0]["name"] == "飞书群"
    assert saved[1]["name"] == "渠道2"  # 名称缺省自动补
    assert store.list_enabled_urls() == [saved[0]["url"]]

    # 无效地址被拒绝
    try:
        store.replace_channels([{"url": "not-a-url"}])
        raise AssertionError("应当抛出 ValueError")
    except ValueError:
        pass

    store.add_log(saved[0]["url"], "notify:test", "测试", True)
    store.add_log(saved[1]["url"], "notify:test", "测试2", False, "HTTP 404")
    logs = store.list_logs()
    assert len(logs) == 2 and logs[0]["ok"] is False  # 新的在前


def test_notify_store_db_mode_roundtrip(tmp_path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from flowpulse.db.engine import ensure_tables

    engine = create_engine(f"sqlite:///{tmp_path}/db.sqlite", future=True)
    ensure_tables(engine)
    store = NotifyStore(
        sessionmaker(bind=engine, expire_on_commit=False, future=True),
        tmp_path / "notify",
    )
    store.replace_channels([{"name": "钉钉", "url": "https://oapi.dingtalk.com/robot/send?token=x"}])
    assert store.list_enabled_urls() == ["https://oapi.dingtalk.com/robot/send?token=x"]

    store.add_log("u", "k", "t", True)
    logs = store.list_logs()
    assert len(logs) == 1 and logs[0]["ok"] is True


def test_notify_api_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: make_settings(tmp_path))
    with TestClient(create_app()) as client:
        # 无环境变量渠道时：空列表 → 保存两条 → 回读（source=db）
        assert client.get("/api/notify/channels").json()["channels"] == []
        saved = client.put(
            "/api/notify/channels",
            json={"channels": [
                {"name": "飞书", "url": "https://open.feishu.cn/open-apis/bot/v2/hook/a"},
                {"name": "备用", "url": "https://example.com/hook", "enabled": False},
            ]},
        ).json()["channels"]
        assert len(saved) == 2 and all(c["source"] == "db" for c in saved)

        # 渠道立即生效：runtime 的 notifier 读同一 store（这里验证 store 数据可见）
        # 测试消息发送：webhook 必须 mock（外网哨兵会拦截真实请求，见 conftest）
        with respx.mock:
            respx.post("https://open.feishu.cn/open-apis/bot/v2/hook/a").respond(json={"ok": True})
            result = client.post("/api/notify/test")
        assert result.status_code == 200 and "sent" in result.json()

        # 日志接口
        logs = client.get("/api/notify/logs").json()["logs"]
        assert isinstance(logs, list)
