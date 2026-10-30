# ported from creatorhub app/browser/xhs_im.py (github.com/3441293738/creatorhub, no license)
# — direct reuse per project decision; see docs/CREATORHUB_FEATURE_MIGRATION_PLAN.md §1
"""小红书 Web 私信只读适配（T4.1）：登录页内第一方 fetch 观察会话与历史。

不合成请求签名、不重连 WebSocket——打开已登录的 /chat 页后，用页面内的
first-party fetch 读取 /api/im/web/* 接口响应（思想与实现移植自 creatorhub）。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

CHAT_URL = "https://www.xiaohongshu.com/chat"
_CHATS_PATH = "/api/im/web/v3/chats"
_UNREAD_PATH = "/api/im/web/chat/get_unread"
_HISTORY_PATH = "/api/im/web/messages/history"
_API_ORIGIN = "https://edith.xiaohongshu.com"


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:  # noqa: BLE001
        return value


def _seconds(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    while number > 10_000_000_000:
        number //= 1000
    return max(0, number)


def _message_text(content: Any) -> tuple[str, str]:
    payload = _json(content)
    if isinstance(payload, str):
        return payload.strip(), "text"
    if not isinstance(payload, dict):
        return "", "unknown"
    raw = payload.get("content")
    if isinstance(raw, dict):
        text = str(raw.get("text") or raw.get("content") or "").strip()
    else:
        text = str(raw or payload.get("text") or "").strip()
    content_type = payload.get("content_type")
    kind = "text" if text else str(content_type or "unknown")
    return text, kind


def parse_conversations(chats_payload: Any, unread_payload: Any = None) -> list[dict]:
    """规范化 /v3/chats 与 get_unread 响应为会话列表。"""
    root = _dict(chats_payload)
    data = _dict(root.get("data"))
    chats = _list(data.get("chats"))

    unread_root = _dict(unread_payload)
    unread_data: Any = unread_root.get("data", unread_root)
    if isinstance(unread_data, dict):
        unread_map = (
            unread_data.get("unread")
            or unread_data.get("unread_map")
            or unread_data.get("result")
            or unread_data
        )
    else:
        unread_map = {}
    unread_map = unread_map if isinstance(unread_map, dict) else {}

    result: list[dict] = []
    seen: set[str] = set()
    for raw in chats:
        item = _dict(raw)
        peer_uid = str(item.get("chat_user_id") or item.get("peer_user_id") or "")
        conv_id = str(item.get("chat_id") or item.get("conversation_id") or peer_uid)
        if not conv_id or conv_id in seen:
            continue
        seen.add(conv_id)
        info = _dict(item.get("info"))
        last_text, _ = _message_text(item.get("last_msg_content"))
        unread = item.get("unread_count")
        if unread is None:
            unread = unread_map.get(peer_uid, unread_map.get(conv_id, 0))
        if isinstance(unread, dict):
            unread = unread.get("count") or unread.get("unread_count") or 0
        try:
            unread = max(0, int(unread or 0))
        except (TypeError, ValueError):
            unread = 0
        result.append(
            {
                "conv_id": conv_id,
                "peer_uid": peer_uid,
                "peer_nickname": str(info.get("nickname") or info.get("name") or ""),
                "peer_avatar": str(info.get("avatar") or info.get("image") or ""),
                "last_text": last_text,
                "last_time": _seconds(item.get("last_msg_time") or item.get("update_time")),
                "unread_count": unread,
                "group_chat": bool(item.get("group_chat") or item.get("is_group_chat")),
            }
        )
    return result


def parse_history(payload: Any, *, peer_uid: str = "", self_uid: str = "") -> dict:
    """规范化历史消息响应：messages / next_cursor / has_more。"""
    root = _dict(payload)
    data = _dict(root.get("data"))
    rows = _list(data.get("out_message_list") or data.get("message_list"))
    messages: list[dict] = []
    store_ids: list[int] = []
    for raw in rows:
        item = _dict(raw)
        sender = str(item.get("sender_id") or item.get("sender_uid") or "")
        receiver = str(item.get("receiver_id") or item.get("receiver_uid") or "")
        text, msg_type = _message_text(item.get("content"))
        store_id = int(item.get("store_id") or 0)
        if store_id:
            store_ids.append(store_id)
        msg_id = str(item.get("id") or item.get("uuid") or store_id or "")
        direction = "out" if self_uid and sender == self_uid else "in"
        if not self_uid and peer_uid:
            direction = "in" if sender == peer_uid else "out"
        messages.append(
            {
                "server_msg_id": msg_id,
                "sender_uid": sender,
                "receiver_uid": receiver,
                "direction": direction,
                "text": text,
                "msg_type": msg_type,
                "create_time": _seconds(item.get("created_at") or item.get("create_time")),
                "store_id": store_id,
            }
        )
    messages.sort(key=lambda row: (int(row.get("create_time") or 0), int(row.get("store_id") or 0)))
    return {
        "messages": messages,
        "next_cursor": min(store_ids) if store_ids else 0,
        "has_more": bool(rows) and len(rows) >= 50,
    }


async def _page_json(page: Any, url: str) -> Any:
    """在已登录页面内发起第一方 fetch（免重载 /chat、免二次签名）。"""
    return await page.evaluate(
        """async (url) => {
            const response = await fetch(url, {
                method: 'GET', credentials: 'include', cache: 'no-store'
            });
            let body = null;
            try { body = await response.json(); } catch (_) {}
            return {status: response.status, body};
        }""",
        url,
    )


async def fetch_conversations_in_page(page: Any, *, pages: int = 1) -> tuple[list[dict], str]:
    """页内拉取会话列表（含未读数）。"""
    payloads: list[dict] = []
    unread_payload: Any = None
    try:
        unread_result = await _page_json(page, f"{_API_ORIGIN}{_UNREAD_PATH}")
        if int(_dict(unread_result).get("status") or 0) == 200:
            unread_payload = _dict(unread_result).get("body")
        for number in range(max(1, min(5, int(pages)))):
            url = f"{_API_ORIGIN}{_CHATS_PATH}?limit=100&complete=true&page={number}&source=pc"
            result = _dict(await _page_json(page, url))
            if int(result.get("status") or 0) != 200:
                return [], f"私信会话接口 HTTP {result.get('status')}"
            payload = _dict(result.get("body"))
            if payload.get("success") is False or str(payload.get("code", "0")) not in {"0", ""}:
                return [], f"私信会话接口返回异常 code={payload.get('code')}"
            payloads.append(payload)
            rows = _list(_dict(payload.get("data")).get("chats"))
            if not rows or len(rows) < 100:
                break
        combined: list[dict] = []
        seen: set[str] = set()
        for payload in payloads:
            for item in parse_conversations(payload, unread_payload):
                key = str(item.get("conv_id") or "")
                if key and key not in seen:
                    seen.add(key)
                    combined.append(item)
        return combined, ""
    except Exception as exc:  # noqa: BLE001
        return [], f"小红书私信同步失败: {exc!r}"


async def fetch_history_in_page(
    page: Any, conv_id: str, *, peer_uid: str = "", self_uid: str = "",
    last_id: int = 0, count: int = 50,
) -> tuple[dict, str]:
    """页内读取单个会话历史（不标已读）。"""
    chat_user_id = str(peer_uid or conv_id or "")
    if not chat_user_id:
        return {}, "缺会话 id"
    url = (
        f"{_API_ORIGIN}{_HISTORY_PATH}?chat_user_id={quote(chat_user_id, safe='')}"
        f"&last_id={max(0, int(last_id))}&limit={max(1, min(100, int(count)))}"
    )
    try:
        result = _dict(await _page_json(page, url))
        if int(result.get("status") or 0) != 200:
            return {}, f"私信历史接口 HTTP {result.get('status')}"
        payload = _dict(result.get("body"))
        if payload.get("success") is False or str(payload.get("code", "0")) not in {"0", ""}:
            return {}, f"私信历史接口返回异常 code={payload.get('code')}"
        parsed = parse_history(payload, peer_uid=chat_user_id, self_uid=self_uid)
        parsed["has_more"] = len(parsed.get("messages", [])) >= max(1, int(count))
        return parsed, ""
    except Exception as exc:  # noqa: BLE001
        return {}, f"小红书私信历史同步失败: {exc!r}"
