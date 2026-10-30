# ported from creatorhub app/platforms/kuaishou/extract.py + app/browser/ks_fetcher.py
# (github.com/3441293738/creatorhub, no license) — direct reuse per project decision
"""快手 GraphQL/REST 响应解析：多候选键兜底（快手字段随版本变化多）。"""

from __future__ import annotations

from typing import Any


def _first(d: dict, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _to_int(value) -> int:
    """快手计数常是字符串（'1.2万'），尽量转整数。"""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        try:
            if s.endswith("万"):
                return int(float(s[:-1]) * 10000)
            if s.endswith("亿"):
                return int(float(s[:-1]) * 100000000)
            return int(float(s))
        except (ValueError, TypeError):
            return 0
    return 0


def _dig_rest_feeds(data: dict) -> list:
    """从 /rest/v/profile/feed 响应里挖出作品数组（feeds / list / photos 兜底）。"""
    if not isinstance(data, dict):
        return []
    for key in ("feeds", "list", "photos"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    d = data.get("data") or {}
    if isinstance(d, dict):
        for key in ("feeds", "list", "photos"):
            v = d.get(key)
            if isinstance(v, list):
                return v
    return []


def _dig_feeds(data: dict) -> list:
    """从 GraphQL 响应里挖出作品 feeds（profile / search / V2 兜底）。"""
    d = (data or {}).get("data") or {}
    for key in ("visionProfilePhotoList", "visionSearchPhoto", "visionProfilePhotoListV2", "feeds"):
        v = d.get(key)
        if isinstance(v, dict) and isinstance(v.get("feeds"), list):
            return v["feeds"]
        if isinstance(v, list):
            return v
    return []


def _search_feeds(data: dict) -> list:
    """兼容快手 REST 搜索与 GraphQL 搜索的常见响应外形。"""
    values = _dig_rest_feeds(data) or _dig_feeds(data)
    if values:
        return values
    payload = (data or {}).get("data") if isinstance(data, dict) else None
    if isinstance(payload, dict):
        for key in ("visionSearchPhoto", "searchPhoto", "photoList"):
            value = payload.get(key)
            if isinstance(value, dict):
                values = value.get("feeds") or value.get("list") or []
                if isinstance(values, list):
                    return values
    return []


def normalize_ks_feed(feed: Any) -> dict | None:
    """规范化一个 feed（visionProfilePhotoList.feeds[] / visionSearchPhoto.feeds[] / REST feeds[]）。"""
    if not isinstance(feed, dict):
        return None
    photo = _first(feed, "photo", default={}) or {}
    if not isinstance(photo, dict):
        photo = {}
    author = _first(feed, "author", default={}) or photo.get("author") or {}
    if not isinstance(author, dict):
        author = {}
    photo_id = str(
        _first(photo, "id", "photoId", default="") or _first(feed, "id", default="") or ""
    )
    if not photo_id:
        return None
    title = str(_first(photo, "caption", "captionWithEmojiTrans", default="") or "").strip()
    ts = _to_int(_first(photo, "timestamp", "createTime", default=0))
    create_time = ts // 1000 if ts > 10_000_000_000 else ts  # 快手时间戳是毫秒
    cover = _first(photo, "coverUrl", "webpCoverUrl", default="") or ""
    if isinstance(cover, list):
        cover = (cover[0].get("url") if isinstance(cover[0], dict) else cover[0]) if cover else ""
    media_type = "video" if _first(photo, "photoUrl", "mainMvUrl", default="") else (
        "images" if (_first(photo, "atlas", default={}) or (_first(photo, "ext_params", default={}) or {}).get("atlas")) else "video"
    )
    return {
        "photo_id": photo_id,
        "title": title[:200],
        "author": str(_first(author, "name", "userName", default="") or ""),
        "author_id": str(_first(author, "userId", "eid", default="") or ""),
        "url": f"https://www.kuaishou.com/short-video/{photo_id}",
        "cover": str(cover),
        "media_type": media_type,
        "liked_count": str(_to_int(_first(photo, "realLikeCount", "likeCount", default=0))),
        "create_time": create_time,
        "extra": {
            "comment_count": _to_int(_first(photo, "commentCount", default=0)),
            "duration_ms": _to_int(_first(photo, "duration", default=0)),
        },
    }
