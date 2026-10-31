"""抖音私信（T4.4）测试：protobuf 编解码往返、access_key、WS 帧解码（构造真实帧）、服务 mock。"""

import gzip
import time

import pytest

from flowpulse.modules.douyin.dm import ws as im_ws
from flowpulse.modules.douyin.dm.protocol import (
    _build_envelope,
    _enc_ld,
    _enc_v,
    _get_fields,
    _first,
    _s,
    build_history_request,
    build_init_request,
    parse_conversations,
    parse_messages,
    parse_send_response,
)
from flowpulse.modules.douyin.dm.service import DouyinDmService


# ---- protobuf 编解码往返 ----


def test_envelope_roundtrip():
    body = _enc_ld(1, b"hello") + _enc_v(2, 42)
    env = _build_envelope(301, _enc_ld(301, body))
    fields = _get_fields(env)
    assert _first(fields, 1) == 301  # cmd
    inner = _first(fields, 8)  # body 挂 field 8
    assert isinstance(inner, bytes)
    body301 = _first(_get_fields(inner), 301)
    assert isinstance(body301, bytes)
    assert _s(_first(_get_fields(body301), 1)) == "hello"


def test_build_requests_shape():
    init = build_init_request(1730000000000000)
    fields = _get_fields(init)
    assert _first(fields, 1) == 2043
    hist = build_history_request("0:1:111111:222222", 1, 555, 0, 20)
    assert _first(_get_fields(hist), 1) == 301
    assert len(init) > 100 and len(hist) > 100


def test_parse_send_response_pb_and_json():
    ok_pb = _enc_v(1, 2043) + _enc_ld(4, b"OK")
    assert parse_send_response(ok_pb) == {"ok": True, "msg": "OK", "cmd": 2043, "error_code": 0}
    bad_pb = _enc_v(1, 100) + _enc_ld(4, b"FAIL") + _enc_v(3, 4)
    result = parse_send_response(bad_pb)
    assert result["ok"] is False and result["error_code"] == 4


# ---- access_key / WS URL ----


def test_compute_access_key_and_url():
    assert len(im_ws.compute_access_key("123")) == 32
    url = im_ws.build_ws_url("42")
    assert url.startswith("wss://frontier-im.douyin.com/ws/v2?aid=6383")
    assert "device_id=42" in url and "access_key=" in url


# ---- WS 推送帧解码（构造 PushFrame → Response → NewMessageNotify → MessageBody） ----


def _build_push_frame(conv_id: str, text: str, sender: str) -> bytes:
    import json

    content = json.dumps({"text": text}, ensure_ascii=False).encode()
    message_body = (
        _enc_ld(1, conv_id.encode())
        + _enc_ld(3, b"m1")
        + _enc_v(6, 7)  # msg_type=7 文本
        + _enc_ld(7, sender.encode())
        + _enc_ld(8, content)
        + _enc_v(5, 1730000000000000)  # 微秒排序索引
    )
    notify = _enc_ld(2, conv_id.encode()) + _enc_ld(5, message_body)
    body = _enc_ld(500, notify)
    response = _enc_ld(6, body)
    return (
        _enc_ld(7, b"pb")
        + _enc_ld(8, response)
    )


def test_decode_push_frame():
    frame = _build_push_frame("0:1:111111:222222", "在吗", "111111")
    messages = im_ws.decode_push_frame(frame, self_uid="222222")
    assert len(messages) == 1
    msg = messages[0]
    assert msg["conv_id"] == "0:1:111111:222222"
    assert msg["text"] == "在吗"
    assert msg["peer_uid"] == "111111"  # 对端 = 非 self 的那个
    assert msg["is_self"] is False


def test_decode_push_frame_gzip_and_heartbeat():
    frame = _build_push_frame("0:1:111111:222222", "hi", "111111")
    # gzip 压缩 payload 字段（field 8）构造 gzip 帧
    fields = _get_fields(frame)
    payload = _first(fields, 8)
    gzipped = gzip.compress(payload)
    gz_frame = _enc_ld(6, b"gzip") + _enc_ld(8, gzipped)
    messages = im_ws.decode_push_frame(gz_frame, self_uid="222222")
    assert len(messages) == 1 and messages[0]["text"] == "hi"
    # 非消息帧（无 field 8 payload）→ 空列表
    assert im_ws.decode_push_frame(_enc_v(1, 1)) == []


# ---- parse_conversations（构造 2043 响应） ----


def test_parse_conversations():
    import json

    conv_id = "0:1:111111:222222"
    content = json.dumps({"text": "你好"}).encode()
    core = (
        _enc_ld(1, conv_id.encode())
        + _enc_v(2, 555)  # short_id
        + _enc_v(3, 1)  # type=1 单聊
        + _enc_ld(4, b"ticket_x")
    )
    last_msg = (
        _enc_v(6, 7)
        + _enc_ld(7, b"111111")
        + _enc_ld(8, content)
        + _enc_v(5, 1730000000000000)
    )
    wrapper = _enc_ld(1, core) + _enc_ld(2, last_msg)
    body2043 = _enc_ld(1, wrapper)
    body = _enc_ld(2043, body2043)
    envelope = _enc_v(1, 2043) + _enc_ld(4, b"OK") + _enc_ld(6, body) + _enc_ld(13, b"222222")
    conversations = parse_conversations(envelope)
    assert len(conversations) == 1
    conv = conversations[0]
    assert conv["conv_id"] == conv_id
    assert conv["peer_uid"] == "111111"  # self=222
    assert conv["ticket"] == "ticket_x"
    assert conv["last_text"] == "你好"
    assert conv["self_uid"] == "222222"


# ---- 服务层（mock 网络） ----


class FakeDmService(DouyinDmService):
    """绕过网络与账号校验：直接注入伪响应。"""

    def __init__(self, conversations_raw: bytes):
        super().__init__(lambda: ("sessionid=x; ttwid=y", None))
        self._conversations_raw = conversations_raw

    async def _post_pb(self, url, body, cookie):
        return self._conversations_raw


@pytest.mark.asyncio
async def test_service_conversations_with_fake_raw():
    import json

    conv_id = "0:1:888888:999999"
    content = json.dumps({"text": "多少钱"}).encode()
    core = _enc_ld(1, conv_id.encode()) + _enc_v(3, 1) + _enc_ld(4, b"tk")
    last = _enc_ld(8, content) + _enc_v(6, 7) + _enc_ld(7, b"888888")
    wrapper = _enc_ld(1, core) + _enc_ld(2, last)
    envelope = (
        _enc_v(1, 2043) + _enc_ld(4, b"OK")
        + _enc_ld(6, _enc_ld(2043, _enc_ld(1, wrapper)))
        + _enc_ld(13, b"999999")
    )
    service = FakeDmService(envelope)
    conversations = await service.conversations()
    assert len(conversations) == 1
    assert conversations[0]["last_text"] == "多少钱"
    service.remember_self_uid(conversations)
    assert service._self_uid_hint == "999999"


@pytest.mark.asyncio
async def test_service_requires_account():
    service = DouyinDmService(lambda: (None, None))
    with pytest.raises(RuntimeError, match="未配置抖音账号"):
        await service.conversations()
