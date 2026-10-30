"""P4 测试：风控闸（配额/冷却/安静时段/接入发布）、小红书私信解析与规则草稿、API。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.platforms.risk import RiskGate
from flowpulse.modules.xhs.dm import reader
from flowpulse.modules.xhs.dm.rules import DmRuleStore
from flowpulse.modules.xhs.dm.service import XhsDmService


# ---- T4.3 风控闸 ----


def test_risk_gate_quotas(tmp_path: Path):
    gate = RiskGate(tmp_path / "risk.json", hourly_limit=2, daily_limit=3, quiet_hours="")
    for _ in range(2):
        assert gate.preflight("douyin", "default")[0] is True
        gate.record_success("douyin", "default")
    ok, reason = gate.preflight("douyin", "default")
    assert ok is False and "小时配额" in reason
    # 其他账号互不影响
    assert gate.preflight("douyin", "other")[0] is True


def test_risk_gate_failure_cooldown_ladder(tmp_path: Path):
    gate = RiskGate(tmp_path / "risk.json", quiet_hours="")
    assert gate.record_failure("xhs", "a") == 1800  # 第 1 次：30 分钟
    ok, reason = gate.preflight("xhs", "a")
    assert ok is False and "冷却" in reason
    # 成功重置连续失败
    gate.clear("xhs", "a")
    gate.record_failure("xhs", "a")
    gate.record_failure("xhs", "a")
    assert gate.record_failure("xhs", "a") == 21600  # 第 3 次：6 小时
    status = gate.status("xhs", "a")
    assert status["paused"] is True and status["consecutive_failures"] == 3


def test_risk_gate_quiet_hours(tmp_path: Path):
    gate = RiskGate(tmp_path / "risk.json", quiet_hours="23:00-07:00")
    from datetime import datetime

    assert gate._in_quiet_hours(datetime(2026, 10, 30, 23, 30)) is True
    assert gate._in_quiet_hours(datetime(2026, 10, 30, 3, 0)) is True  # 跨午夜
    assert gate._in_quiet_hours(datetime(2026, 10, 30, 12, 0)) is False


@pytest.mark.asyncio
async def test_publish_blocked_by_risk_keeps_pending(tmp_path: Path, monkeypatch):
    from flowpulse.modules.douyin.publish.service import DouyinPublishService
    from flowpulse.modules.douyin.publish.store import DouyinPublishStore

    media = tmp_path / "downloads" / "t1"
    media.mkdir(parents=True)
    (media / "a.mp4").write_bytes(b"0" * 8)

    gate = RiskGate(tmp_path / "risk.json", hourly_limit=1, quiet_hours="")
    service = DouyinPublishService(
        DouyinPublishStore(None, tmp_path), tmp_path, lambda: (None, None),
        tmp_path / "profiles", enabled=False, risk_gate=gate,
    )
    task = service.create_draft({"title": "x", "media_paths": ["downloads/t1/a.mp4"]})
    service.submit(task["id"])
    # 第一次：风控通过（配额未耗尽），执行后失败（无账号）并计入冷却
    result = await service.process_next()
    assert result["status"] == "failed"
    # 第二次提交：冷却中 → 拦截，任务保持 pending 并写明原因
    task2 = service.create_draft({"title": "y", "media_paths": ["downloads/t1/a.mp4"]})
    service.submit(task2["id"])
    result2 = await service.process_next()
    assert result2["status"] == "pending"
    assert "风控拦截" in result2["error"] and "冷却" in result2["error"]


# ---- T4.1 私信解析（结构参照 creatorhub 响应形态） ----


def test_parse_conversations_and_history():
    chats_payload = {
        "data": {
            "chats": [
                {
                    "chat_id": "c1",
                    "chat_user_id": "u9",
                    "user_id": "me",
                    "info": {"nickname": "小明", "avatar": "https://a/x.webp"},
                    "last_msg_content": '{"content":{"text":"多少钱"},"content_type":1}',
                    "last_msg_time": 1730000000000,  # 毫秒 → 秒
                    "unread_count": 2,
                },
                {"chat_id": "c1", "chat_user_id": "dup"},  # 重复去重
            ]
        }
    }
    conversations = reader.parse_conversations(chats_payload, {"data": {"unread": {}}})
    assert len(conversations) == 1
    conv = conversations[0]
    assert conv["peer_nickname"] == "小明" and conv["last_text"] == "多少钱"
    assert conv["unread_count"] == 2 and conv["last_time"] == 1730000000

    history_payload = {
        "data": {
            "out_message_list": [
                {"sender_id": "u9", "content": '{"content":{"text":"在吗"}}', "store_id": 2,
                 "created_at": 1730000001},
                {"sender_id": "me", "content": "在的", "store_id": 3, "created_at": 1730000002},
            ]
        }
    }
    parsed = reader.parse_history(history_payload, peer_uid="u9", self_uid="me")
    assert [m["text"] for m in parsed["messages"]] == ["在吗", "在的"]
    assert parsed["messages"][0]["direction"] == "in"
    assert parsed["messages"][1]["direction"] == "out"


# ---- T4.2 规则与草稿 ----


def test_rule_match_generates_pending_draft(tmp_path: Path):
    store = DmRuleStore(None, tmp_path)
    rule = store.create_rule(
        {"name": "价格咨询", "keywords": "多少钱,价格", "reply_template": "亲，稍后回复您报价～"}
    )
    service = XhsDmService(object(), tmp_path, store)  # xhs_service 仅同步时使用
    conversations = [
        {"conv_id": "c1", "peer_uid": "u9", "peer_nickname": "小明",
         "last_text": "这个多少钱", "unread_count": 2},
        {"conv_id": "c2", "peer_uid": "u8", "peer_nickname": "小红",
         "last_text": "看看", "unread_count": 1},  # 不命中
        {"conv_id": "c3", "peer_uid": "u7", "peer_nickname": "已读",
         "last_text": "多少钱", "unread_count": 0},  # 无未读不生成
    ]
    created = service.generate_drafts(conversations)
    assert created == 1
    drafts = store.list_drafts(status="pending")
    assert drafts[0]["conv_id"] == "c1" and drafts[0]["rule_name"] == "价格咨询"
    # 同会话同消息不重复生成
    assert service.generate_drafts(conversations) == 0
    # 审核
    reviewed = store.review_draft(drafts[0]["id"], "approved")
    assert reviewed["status"] == "approved"
    assert store.list_drafts(status="pending") == []


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
        risk_enabled=False,  # 关掉风控避免影响其它测试路径
    )


def test_dm_rules_api(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        # 规则 CRUD
        created = client.post(
            "/api/v1/xhs/dm/rules",
            json={"name": "价格", "keywords": "多少钱", "reply_template": "稍后报价"},
        )
        assert created.status_code == 201
        rule = created.json()
        assert client.get("/api/v1/xhs/dm/rules").json()["rules"][0]["name"] == "价格"
        patched = client.patch(
            f"/api/v1/xhs/dm/rules/{rule['id']}", json={"enabled": False}
        ).json()
        assert patched["enabled"] is False
        assert client.delete(f"/api/v1/xhs/dm/rules/{rule['id']}").json()["deleted"] is True

        # 未登录小红书时会话同步 400（浏览器层前置校验）
        resp = client.get("/api/v1/xhs/dm/conversations")
        assert resp.status_code == 400 and "未登录" in resp.json()["detail"]

        # 草稿审核参数校验
        assert client.post("/api/v1/xhs/dm/drafts/1/review", params={"decision": "bad"}).status_code == 400
