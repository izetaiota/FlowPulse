"""抖音私信服务（T4.4，直接移植 creatorhub）：纯协议会话快照 + 历史消息 + 实时 WS。

三条通道（均纯 Cookie 鉴权，无需浏览器、无需 a_bogus 签名）：
- 会话快照：POST imapi get_message_by_init（cmd 2043，protobuf body）→ parse_conversations
- 历史消息：POST imapi get_by_conversation（cmd 301）→ parse_messages
- 实时接收：frontier-im WebSocket（access_key=md5(fpid+appKey+uid+salt)，device_id=账号 uid）

依赖 curl_cffi（xhs 可选组）；未安装时优雅报错。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from flowpulse.modules.douyin.dm.protocol import (
    GET_BY_CONV_URL,
    GET_MESSAGE_BY_INIT_URL,
    build_history_request,
    build_init_request,
    parse_conversations,
    parse_messages,
    parse_send_response,
)
from flowpulse.modules.douyin.dm import ws as im_ws

IM_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def _require_curl_cffi():
    try:
        import curl_cffi  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("未安装 curl_cffi（pip install -e \".[xhs]\"），抖音私信不可用") from exc


def _im_headers(cookie: str) -> dict:
    return {
        "Cookie": cookie,
        "User-Agent": IM_UA,
        "Accept": "application/x-protobuf",
        "Content-Type": "application/x-protobuf",
        "Origin": "https://www.douyin.com",
        "Referer": "https://www.douyin.com/",
    }


class DouyinDmService:
    def __init__(self, get_login_state):
        """get_login_state: () -> (cookie_str | None, storage_state | None)。"""

        self._get_login_state = get_login_state
        self._last_error = ""

    @property
    def last_error(self) -> str:
        return self._last_error

    def _cookie(self) -> str:
        cookie, _ = self._get_login_state()
        if not cookie:
            raise RuntimeError("未配置抖音账号：请先在「作品监控」页扫码登录或导入 Cookie")
        return cookie

    async def _post_pb(self, url: str, body: bytes, cookie: str) -> bytes:
        from curl_cffi.requests import AsyncSession

        async with AsyncSession(impersonate="chrome124") as session:
            response = await session.post(
                url, data=body, headers=_im_headers(cookie), timeout=30
            )
            if response.status_code != 200:
                raise RuntimeError(f"imapi 返回 HTTP {response.status_code}")
            raw = bytes(response.content or b"")
            if not raw:
                raise RuntimeError("imapi 返回空响应")
            return raw

    # ---- 会话快照（cmd 2043） ----

    async def conversations(self) -> list[dict]:
        _require_curl_cffi()
        cookie = self._cookie()
        body = build_init_request(int(time.time() * 1_000_000))
        raw = await self._post_pb(GET_MESSAGE_BY_INIT_URL, body, cookie)
        status = parse_send_response(raw)
        if not status.get("ok") or status.get("cmd") != 2043:
            self._last_error = f"imapi 拒绝：{status.get('msg') or status.get('error_code')}"
            return []
        self._last_error = ""
        return parse_conversations(raw)

    # ---- 历史消息（cmd 301） ----

    async def history(
        self, conv_id: str, conv_short_id: str, conv_type: int = 1,
        cursor: int = 0, count: int = 50,
    ) -> dict:
        _require_curl_cffi()
        if not conv_id or not conv_short_id:
            raise ValueError("缺 conv_id / conv_short_id")
        cookie = self._cookie()
        body = build_history_request(
            conv_id, int(conv_type or 1), int(conv_short_id), int(cursor or 0), count
        )
        raw = await self._post_pb(GET_BY_CONV_URL, body, cookie)
        return parse_messages(raw)

    # ---- 实时接收（frontier WS） ----

    @staticmethod
    def decode_frame(raw: bytes, self_uid: str = "") -> list[dict]:
        return im_ws.decode_push_frame(raw, self_uid)

    async def receive(
        self,
        on_message: Callable[[dict], None],
        stop_after: float | None = None,
        should_stop: Callable[[], bool] | None = None,
        log: Callable[[str], None] = lambda _s: None,
    ) -> str:
        """连 frontier-im WS 持续接收新消息（断线自动重连）。需 websockets 库。"""
        try:
            import websockets  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("未安装 websockets（pip install websockets），实时接收不可用") from exc
        cookie = self._cookie()
        # device_id 实测 == 账号自身 uid；从 cookie 的 sessionid 拿不到 uid，
        # 由调用方从会话快照的 self_uid 传入更稳——这里从最近一次快照缓存读取
        device_id = self._self_uid_hint
        if not device_id:
            raise RuntimeError("缺少 device_id（先调一次会话快照以获取 self_uid）")
        self_uid = device_id
        return await im_ws.receive_messages(
            cookie, device_id, on_message,
            self_uid=self_uid, stop_after=stop_after, should_stop=should_stop, log=log,
        )

    _self_uid_hint: str = ""

    def remember_self_uid(self, conversations: list[dict]) -> None:
        for row in conversations or []:
            uid = str(row.get("self_uid") or "")
            if uid:
                self._self_uid_hint = uid
                return
