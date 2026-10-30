"""T4.2 发送闭环测试：payload_result 纯函数、mark_sent 状态、send_draft（mock 页面/风控）。"""

from pathlib import Path

import pytest

from flowpulse.modules.platforms.risk import RiskGate
from flowpulse.modules.xhs.dm.rules import DmRuleStore
from flowpulse.modules.xhs.dm.sender import payload_result
from flowpulse.modules.xhs.dm.service import XhsDmService


def test_payload_result():
    assert payload_result({"success": True}) == "accepted"
    assert payload_result({"data": {"success": True}}) == "accepted"
    assert payload_result({"code": 0}) == "accepted"
    assert payload_result({"success": False}) == "rejected"
    assert payload_result({"code": -1}) == "rejected"
    assert payload_result({"data": {"success": False}}) == "rejected"
    assert payload_result("junk") == "unknown"
    assert payload_result({"foo": 1}) == "unknown"


def test_mark_sent_flow(tmp_path: Path):
    store = DmRuleStore(None, tmp_path)
    draft = store.create_draft({"conv_id": "c1", "last_text": "x", "suggested_reply": "回"})
    store.review_draft(draft["id"], "approved")
    # 发送失败：保持 approved 可重试 + error 记录
    failed = store.mark_sent(draft["id"], False, "write_uncertain:xxx")
    assert failed["status"] == "approved" and "write_uncertain" in failed["error"]
    # 发送成功：sent + sent_at
    sent = store.mark_sent(draft["id"], True)
    assert sent["status"] == "sent" and sent["sent_at"]
    assert sent["error"] == ""


@pytest.mark.asyncio
async def test_send_draft_risk_blocked(tmp_path: Path):
    store = DmRuleStore(None, tmp_path)
    draft = store.create_draft(
        {"conv_id": "c1", "peer_uid": "u9", "last_text": "x", "suggested_reply": "回"}
    )
    store.review_draft(draft["id"], "approved")
    gate = RiskGate(tmp_path / "risk.json", hourly_limit=0, quiet_hours="")  # 0 = 不限
    gate.record_failure("xhs", "pc")  # 制造冷却
    service = XhsDmService(object(), tmp_path, store, risk_gate=gate)
    result = await service.send_draft(draft["id"])
    assert result["ok"] is False and "风控拦截" in result["message"]
    # 状态未被改成失败（拦截不消耗重试机会）
    assert store.list_drafts()[0]["status"] == "approved"


@pytest.mark.asyncio
async def test_send_draft_with_fake_page(tmp_path: Path, monkeypatch):
    store = DmRuleStore(None, tmp_path)
    draft = store.create_draft(
        {"conv_id": "c1", "peer_uid": "u9", "last_text": "x", "suggested_reply": "你好"}
    )
    store.review_draft(draft["id"], "approved")
    service = XhsDmService(object(), tmp_path, store)

    calls: dict = {}

    class FakePage:
        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_timeout(self, *args, **kwargs):
            return None

    class FakeContext:
        pages = [FakePage()]

        async def close(self):
            calls["closed"] = True

    class FakeService(XhsDmService):
        async def _open_chat_page(self, headless=True):
            context = FakeContext()
            return context, context.pages[0]

    async def fake_send(page, text, **kwargs):
        calls["text"] = text
        return True, ""

    monkeypatch.setattr("flowpulse.modules.xhs.dm.sender.send_dm_in_page", fake_send)
    service.__class__ = FakeService
    result = await service.send_draft(draft["id"])
    assert result["ok"] is True and calls["text"] == "你好" and calls["closed"] is True
    assert store.list_drafts()[0]["status"] == "sent"
    # 未审核的草稿不可发送
    draft2 = store.create_draft({"conv_id": "c2", "last_text": "y", "suggested_reply": "z"})
    with pytest.raises(ValueError):
        await service.send_draft(draft2["id"])
