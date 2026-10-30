# ported from creatorhub app/platforms/tiktok/extract.py (github.com/3441293738/creatorhub,
# no license) — direct reuse per project decision；Aweme 数据类适配为本项目监控 dict 结构
"""TikTok 响应解析：搜索 item / 评论（含楼中楼展开）。"""

from __future__ import annotations

import time
from typing import Any, Optional


def _first(data: dict, *keys, default=None):
    if not isinstance(data, dict):
        return default
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def tiktok_display_text(value) -> str:
    """TikTok 文案常带 emoji 转义（\\ud83d\\ude00），清洗为可读文本。"""
    text = str(value or "")
    try:
        text = text.encode("utf-16", "surrogatepass").decode("utf-16")
    except Exception:  # noqa: BLE001
        pass
    return text.strip()


def _url(value) -> str:
    if isinstance(value, dict):
        value = value.get("url_list") or value.get("url") or ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "") if str(value or "").startswith("http") else ""


def _item(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    value = raw.get("item") or raw.get("aweme_info") or raw.get("itemStruct") or raw
    return value if isinstance(value, dict) else {}


def video_url(aweme_id: str, author_unique_id: str) -> str:
    return f"https://www.tiktok.com/@{author_unique_id or 'user'}/video/{aweme_id}"


def normalize_tiktok_item(raw: Any) -> Optional[dict]:
    """搜索 item → 监控作品 dict（无下载地址也返回，元数据本身有价值）。"""
    item = _item(raw if isinstance(raw, dict) else {})
    aweme_id = str(_first(item, "id", "aweme_id", "itemId", default="") or "")
    if not aweme_id:
        return None
    author = item.get("author") or {}
    author_unique_id = str(_first(author, "uniqueId", "unique_id", default="") or "")
    stats = item.get("stats") or item.get("statistics") or {}
    video = item.get("video") or {}
    create_time = _int(_first(item, "createTime", "create_time", default=0))
    if create_time > 10_000_000_000:
        create_time //= 1000
    if not create_time and aweme_id.isdigit():
        # TikTok 64 位作品 ID 高 32 位通常是 Unix 秒：卡片省略 createTime 时补全，
        # 避免基线误判（见 creatorhub 同款注释）
        candidate = int(aweme_id) >> 32
        if 1_450_000_000 <= candidate <= int(time.time()) + 86400:
            create_time = candidate
    nickname = tiktok_display_text(_first(author, "nickname", "uniqueId", default=""))
    return {
        "aweme_id": aweme_id,
        "title": tiktok_display_text(_first(item, "desc", "description", default=""))[:200],
        "author": nickname or (f"@{author_unique_id}" if author_unique_id else ""),
        "author_id": author_unique_id,
        "url": video_url(aweme_id, author_unique_id),
        "cover": _url(_first(video, "cover", "dynamicCover", "originCover", default={})),
        "media_type": "video",
        "liked_count": str(_int(_first(stats, "diggCount", "digg_count", default=0))),
        "create_time": create_time,
        "extra": {
            "comment_count": _int(_first(stats, "commentCount", "comment_count", default=0)),
            "share_count": _int(_first(stats, "shareCount", "share_count", default=0)),
        },
    }


def parse_tiktok_comment(raw: dict, parent_id: str = "") -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    cid = str(_first(raw, "cid", "id", "comment_id", default="") or "")
    if not cid:
        return None
    user = raw.get("user") or raw.get("author") or {}
    reply_to = str(_first(raw, "reply_id", "replyId", "reply_to", default="") or "")
    if reply_to in {"0", cid}:
        reply_to = ""
    if not reply_to:
        reply_to = str(parent_id or "")
    return {
        "comment_id": cid,
        "text": str(_first(raw, "text", "content", default="") or "").strip(),
        "user_nickname": str(_first(user, "nickname", "uniqueId", "unique_id", default="") or ""),
        "user_sec_uid": str(_first(user, "secUid", "sec_uid", "uid", "id", default="") or ""),
        "ip_label": str(_first(raw, "ip_label", "ipLabel", default="") or ""),
        "like_count": _int(_first(raw, "digg_count", "diggCount", "like_count", default=0)),
        "create_time": _int(_first(raw, "create_time", "createTime", default=0)),
        "reply_to": reply_to,
    }


def flatten_tiktok_comments(comments: list, include_replies: bool = True) -> list:
    output: list[dict] = []
    for root in comments or []:
        if not isinstance(root, dict):
            continue
        output.append(root)
        if not include_replies:
            continue
        parent = str(_first(root, "cid", "id", "comment_id", default="") or "")
        replies = (
            root.get("reply_comment")
            or root.get("replyComments")
            or root.get("replies")
            or root.get("children")
            or []
        )
        for reply in replies if isinstance(replies, list) else []:
            if isinstance(reply, dict):
                value = dict(reply)
                value.setdefault("reply_id", parent)
                output.append(value)
    return output
