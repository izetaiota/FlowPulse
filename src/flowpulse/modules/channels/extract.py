# ported from creatorhub app/platforms/channels/extract.py + app/browser/channels_fetcher.py
# (github.com/3441293738/creatorhub, no license) — direct reuse per project decision
"""视频号（微信 Channels）响应解析：mmfinderassistant-bin 统一 {errCode,data} 包装，多候选键兜底。

与其它平台不同：视频号媒体走加密 CDN（encfilekey），多数拿不到明文直链——
作品即使无媒体 URL 也返回（只记元数据 + 统计）。
"""

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
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (ValueError, TypeError):
            return 0
    return 0


def dig_data(data: Any) -> dict:
    """mmfinderassistant 统一包一层 {errCode, data:{...}}；取出 data。"""
    if not isinstance(data, dict):
        return {}
    inner = data.get("data")
    return inner if isinstance(inner, dict) else data


def dig_posts(data: Any) -> list:
    """从 post_list 响应里挖出作品数组（list / post_list / object_list 兜底）。"""
    d = dig_data(data)
    for key in ("list", "post_list", "object_list", "objectList", "feeds", "posts"):
        v = d.get(key)
        if isinstance(v, list):
            return v
    return []


def parse_profile(data: Any) -> dict:
    """auth/get_auth_info 响应 → 视频号资料（finderUser / finder / data 本身兜底）。"""
    d = dig_data(data)
    finder = _first(d, "finderUser", "finder", "finderInfo", default=None) or d
    if not isinstance(finder, dict):
        return {}
    nickname = _first(finder, "nickname", "nickName", default="")
    if not nickname:
        return {}
    return {
        "nickname": str(nickname),
        "username": str(_first(finder, "username", "finderUsername", default="") or ""),
        "avatar": str(_first(finder, "headUrl", "avatar", default="") or ""),
        "extra": {"raw_keys": sorted(k for k in finder.keys())[:20]},
    }


def parse_post(item: Any) -> dict | None:
    """post_list 里的一条作品 → 元数据 dict（无媒体也返回，加密 CDN 只记元数据）。"""
    if not isinstance(item, dict):
        return None
    object_id = str(_first(item, "objectId", "exportId", "id", default="") or "")
    if not object_id:
        return None
    object_desc = _first(item, "objectDesc", "desc", default={}) or {}
    if not isinstance(object_desc, dict):
        object_desc = {}
    title = str(
        _first(object_desc, "description", "shortTitle", default="")
        or _first(item, "description", "title", default="")
        or ""
    ).strip()
    ts = _to_int(
        _first(item, "createtime", "createTime", "create_time", "postTime", default=0)
    )
    create_time = ts // 1000 if ts > 10_000_000_000 else ts  # 多为秒级，兜底毫秒

    medias = (
        _first(object_desc, "media", default=None) or _first(item, "media", default=None) or []
    )
    if not isinstance(medias, list):
        medias = []
    first_media = medias[0] if medias and isinstance(medias[0], dict) else {}
    cover = str(
        _first(first_media, "coverUrl", "thumbUrl", "fullCoverUrl", default="")
        or _first(item, "coverUrl", "cover", default="")
        or ""
    )
    fmt = str(_first(first_media, "fileFormat", "mediaType", default="")).lower()
    media_type_code = _first(object_desc, "mediaType", default=None)
    media_type = (
        "images"
        if (media_type_code == 2 or fmt == "2" or "pic" in fmt or "image" in fmt or "img" in fmt)
        else "video"
    )
    # 尽力取明文直链（多数为空——加密 CDN）；有则记入 extra 供人工下载
    plain_urls = []
    for m in medias:
        if isinstance(m, dict):
            url = _first(m, "url", "videoUrl", "originUrl", default="")
            if isinstance(url, str) and url.startswith("http"):
                plain_urls.append(url)
    return {
        "object_id": object_id,
        "title": title[:200],
        "create_time": create_time,
        "cover": cover,
        "media_type": media_type,
        "liked_count": str(_to_int(_first(item, "likeCount", "like_count", "fav", default=0))),
        "comment_count": _to_int(_first(item, "commentCount", "comment_count", default=0)),
        "forward_count": _to_int(_first(item, "forwardCount", "forward_count", default=0)),
        "media_note": "加密 CDN，仅记录元数据" if not plain_urls else "",
        "extra": {"plain_urls": plain_urls[:3]},
    }
