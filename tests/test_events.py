"""P6 测试：Bark/Telegram payload、事件中心（outbox/订阅过滤/HMAC/重试）、API。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.core.notify import WebhookNotifier
from flowpulse.main import create_app
from flowpulse.modules.events import EventCenter


# ---- T6.2 Bark/Telegram payload ----


def test_notify_payload_channel_types():
    notifier = WebhookNotifier(None, "")
    assert notifier._payload("https://api.day.app/mykey", "标题", "内容") == {
        "title": "标题", "body": "内容",
    }
    assert notifier._payload("https://api.telegram.org/bot123/sendMessage?chat_id=456", "标题", "内容") == {
        "text": "标题\n内容",
    }
    assert notifier._payload("https://open.feishu.cn/hook/x", "标题", "内容") == {
        "msg_type": "text", "content": {"text": "标题\n内容"},
    }
    assert notifier._payload("https://oapi.dingtalk.com/robot/send?token=x", "标题", "内容")["msgtype"] == "markdown"


# ---- T6.1 事件中心 ----


def test_emit_skipped_without_subscriptions(tmp_path: Path):
    center = EventCenter(None, tmp_path, None)
    assert center.emit("monitor.new_works", "测试") is None  # 无订阅不写
    center.upsert_subscription("https://example.com/hook")
    event_id = center.emit("monitor.new_works", "测试", {"k": 1})
    assert event_id is not None
    events = center.list_events()
    assert len(events) == 1 and events[0]["status"] == "pending"
    assert events[0]["event_type"] == "monitor.new_works"


def test_subscription_crud_and_filter(tmp_path: Path):
    center = EventCenter(None, tmp_path, None)
    sub = center.upsert_subscription("https://example.com/a", secret="s1", events="risk.cooldown")
    assert sub["events"] == "risk.cooldown"
    # 按 URL 去重更新
    updated = center.upsert_subscription("https://example.com/a", secret="s2", enabled=False)
    assert updated["secret"] == "s2" and updated["enabled"] is False
    assert len(center.list_subscriptions()) == 1
    # 过滤匹配
    assert EventCenter._matches({"events": "risk.cooldown"}, "risk.cooldown") is True
    assert EventCenter._matches({"events": "risk.cooldown"}, "monitor.new_works") is False
    assert EventCenter._matches({"events": ""}, "anything") is True
    assert center.delete_subscription(sub["id"]) is True


@pytest.mark.asyncio
async def test_dispatch_with_hmac_and_retry(tmp_path: Path, monkeypatch):
    import httpx

    center = EventCenter(None, tmp_path, httpx.AsyncClient())
    center.upsert_subscription("https://example.com/hook", secret="topsecret")

    deliveries: list[dict] = []

    async def fake_post(url, content=None, headers=None, timeout=None):
        deliveries.append({"url": url, "body": json.loads(content), "headers": headers})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(center._client, "post", fake_post)
    center.emit("risk.cooldown", "冷却", {"cooldown_seconds": 1800})
    summary = await center.dispatch_pending()
    assert summary == {"dispatched": 1, "delivered": 1, "failed": 0}
    assert deliveries[0]["body"]["event"] == "risk.cooldown"
    sig = deliveries[0]["headers"]["x-flowpulse-signature-256"]
    assert sig.startswith("sha256=") and len(sig) == 7 + 64
    events = center.list_events()
    assert events[0]["status"] == "delivered" and events[0]["attempts"] == 1

    # 失败重试：HTTP 500 → partial/pending，达 MAX_ATTEMPTS 后 failed
    async def fail_post(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(center._client, "post", fail_post)
    center.emit("monitor.new_works", "新作品", {})
    for _ in range(5):
        await center.dispatch_pending()
    events = center.list_events()
    failed = next(e for e in events if e["event_type"] == "monitor.new_works")
    assert failed["status"] == "failed" and failed["attempts"] == 5


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


def test_events_api(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        listing = client.get("/api/v1/events/subscriptions").json()
        assert listing["subscriptions"] == [] and "monitor.new_works" in listing["event_types"]

        created = client.put(
            "/api/v1/events/subscriptions",
            json={"url": "https://example.com/hook", "secret": "s", "events": "risk.cooldown"},
        )
        assert created.status_code == 201
        sub = created.json()
        assert (
            client.put("/api/v1/events/subscriptions", json={"url": "bad-url"}).status_code == 400
        )

        # 无 pending 事件时 dispatch 空跑
        result = client.post("/api/v1/events/dispatch").json()
        assert result == {"dispatched": 0, "delivered": 0, "failed": 0}

        assert client.delete(f"/api/v1/events/subscriptions/{sub['id']}").json()["deleted"] is True
