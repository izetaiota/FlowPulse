"""阶段 2 测试：RSS 输出、Webhook 告警、定时调度器。"""

from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient

from metacorpus.config import Settings
from metacorpus.main import create_app
from weread.models import MpArticle
from weread.notify import WebhookNotifier
from weread.rss import build_rss

WEREAD = "https://weread.qq.com"
BOOK_ID = "MP_WXS_3012726261"
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=test"


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_request_interval_seconds=0,
        weread_sync_interval_minutes=0,
        weread_webhook_url="",
        weread_cookie_refresh_hours=0,
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ---- RSS ----


def test_rss_builder_escapes_and_formats():
    articles = [
        MpArticle(
            review_id="r1",
            book_id=BOOK_ID,
            title="标题<1> & 测试",
            link="https://mp.weixin.qq.com/s/abc_def",
            digest="摘要",
            publish_time=1761549000,
        )
    ]
    xml = build_rss("频道名", "http://x/", "描述", articles)
    assert '<?xml version="1.0" encoding="UTF-8"?>' in xml
    assert "<rss version=\"2.0\">" in xml
    assert "标题&lt;1&gt; &amp; 测试" in xml
    assert "<guid isPermaLink=\"false\">r1</guid>" in xml
    assert "<pubDate>" in xml
    assert "mp.weixin.qq.com/s/abc_def" in xml


@respx.mock
def test_rss_endpoints(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": []})
    respx.get(f"{WEREAD}/api/mp/cover").respond(
        json={"name": "测试号", "reviewId": f"{BOOK_ID}_c1", "title": "第一篇", "pic": "", "avatar": ""}
    )
    respx.get(f"{WEREAD}/web/mp/articles").respond(
        json={
            "reviews": [
                {
                    "createTime": 1761549000,
                    "subReviews": [
                        {
                            "review": {
                                "reviewId": f"{BOOK_ID}_r1~x",
                                "createTime": 1761549000,
                                "mpInfo": {"title": "列表篇", "originalId": "r1~x", "time": 1761549000},
                            }
                        }
                    ],
                }
            ]
        }
    )

    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        client.post("/api/weread/subscriptions", json={"input": BOOK_ID})
        client.post("/api/weread/sync")

        # 单订阅源
        response = client.get(f"/api/weread/rss/{BOOK_ID}.xml")
        assert response.status_code == 200
        assert "rss+xml" in response.headers["content-type"]
        assert "测试号" in response.text
        assert "列表篇" in response.text
        assert "mp.weixin.qq.com/s/r1_x" in response.text

        # 合并源
        response = client.get("/api/weread/rss/all.xml")
        assert response.status_code == 200
        assert "全部" in response.text

        # 未知订阅 → 404
        response = client.get("/api/weread/rss/MP_WXS_404.xml")
        assert response.status_code == 404


# ---- Webhook 通知 ----


def _notifier(url: str) -> WebhookNotifier:
    return WebhookNotifier(httpx.AsyncClient(), url)


def test_webhook_payload_formats():
    dingtalk = _notifier(DINGTALK_WEBHOOK)
    assert dingtalk._payload("标题", "内容") == {
        "msgtype": "markdown",
        "markdown": {"title": "标题", "text": "**标题**\n\n内容"},
    }
    feishu = _notifier("https://open.feishu.cn/open-apis/bot/v2/hook/x")
    assert feishu._payload("标题", "内容") == {
        "msg_type": "text",
        "content": {"text": "标题\n内容"},
    }
    generic = _notifier("https://example.com/hook")
    assert generic._payload("标题", "内容") == {"title": "标题", "text": "内容"}


@respx.mock
async def test_webhook_cooldown():
    route = respx.post(DINGTALK_WEBHOOK).respond(json={"errcode": 0})
    notifier = _notifier(DINGTALK_WEBHOOK)
    first = await notifier.send("key", "t", "m", cooldown_seconds=3600)
    second = await notifier.send("key", "t", "m", cooldown_seconds=3600)
    assert first is True
    assert second is False
    assert route.call_count == 1
    await notifier._client.aclose()


# ---- 调度器 ----


def test_scheduler_status_disabled_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    with TestClient(create_app()) as client:
        status = client.get("/api/weread/scheduler").json()
        assert status["enabled"] is False
        assert status["running"] is False


@respx.mock
def test_scheduler_trigger_sends_auth_alert(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "metacorpus.main.get_settings",
        lambda: make_settings(tmp_path, weread_webhook_url=DINGTALK_WEBHOOK),
    )
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": []})
    cover_route = respx.get(f"{WEREAD}/api/mp/cover")
    cover_route.side_effect = [
        # 添加订阅时成功；随后失效
        httpx.Response(200, json={"name": "测试号", "reviewId": f"{BOOK_ID}_c1", "title": "t", "pic": "", "avatar": ""}),
        httpx.Response(200, json={"errCode": -2012, "errMsg": "timeout"}),
    ]
    respx.get(f"{WEREAD}/web/mp/articles").respond(json={"errCode": -2012, "errMsg": "timeout"})
    webhook_route = respx.post(DINGTALK_WEBHOOK).respond(json={"errcode": 0})

    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        client.post("/api/weread/subscriptions", json={"input": BOOK_ID})

        result = client.post("/api/weread/scheduler/trigger").json()
        assert result["error_count"] == 1
        assert result["ok_count"] == 0

        # 钉钉格式告警已发出（Cookie 失效）
        assert webhook_route.call_count == 1
        payload = webhook_route.calls.last.request
        import json

        body = json.loads(payload.read().decode("utf-8"))
        assert body["msgtype"] == "markdown"
        assert "Cookie" in body["markdown"]["text"]

        # 状态已记录
        status = client.get("/api/weread/scheduler").json()
        assert status["running"] is False
        assert status["last_result"]["error_count"] == 1
        assert status["last_run_at"]


@respx.mock
def test_scheduler_trigger_no_credential_alert(tmp_path: Path, monkeypatch):
    """无凭证触发：记录错误结果并告警（auth 类）。"""
    monkeypatch.setattr(
        "metacorpus.main.get_settings",
        lambda: make_settings(tmp_path, weread_webhook_url=DINGTALK_WEBHOOK),
    )
    webhook_route = respx.post(DINGTALK_WEBHOOK).respond(json={"errcode": 0})

    with TestClient(create_app()) as client:
        result = client.post("/api/weread/scheduler/trigger").json()
        assert "error" in result
        assert webhook_route.call_count == 1
