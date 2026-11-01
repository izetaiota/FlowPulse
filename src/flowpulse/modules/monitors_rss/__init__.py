"""监控 RSS 输出（T1.5）：聚合四平台监控作品为一条 RSS（复用 weread 的生成思路）。

GET /api/rss/monitors.xml?platform=xhs|douyin|ks|tiktok&monitor_id=N
生成最近 50 条监控作品（按发现时间倒序），标题带平台与来源监控前缀。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Response

router = APIRouter(prefix="/api/rss", tags=["rss"])

_FEED_LIMIT = 50


def _entry_time(row: dict) -> str:
    return str(row.get("first_seen_at") or row.get("created_at") or "")


def _entry_title(row: dict) -> str:
    return str(row.get("title") or row.get("aweme_id") or row.get("photo_id") or row.get("note_id") or "")


def _entry_url(row: dict) -> str:
    return str(row.get("url") or "")


def _entry_id(row: dict) -> str:
    return str(row.get("aweme_id") or row.get("photo_id") or row.get("note_id") or row.get("id") or "")


def build_monitor_rss(entries: list[dict], title: str) -> str:
    items: list[str] = []
    for row in entries:
        pub = _entry_time(row)
        parts = [
            f"<title>{escape(_entry_title(row) or '(无标题)')}</title>",
            f"<link>{escape(_entry_url(row))}</link>",
            f'<guid isPermaLink="false">{escape(_entry_id(row))}</guid>',
        ]
        if pub:
            parts.append(f"<pubDate>{escape(pub)}</pubDate>")
        author = str(row.get("author") or "")
        if author:
            parts.append(f"<author>{escape(author)}</author>")
        desc = f"来源监控：{row.get('monitor_name', '')} · 作者：{author} · 点赞 {row.get('liked_count', '')}"
        parts.append(f"<description>{escape(desc)}</description>")
        items.append("<item>" + "".join(parts) + "</item>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<rss version="2.0"><channel><title>{escape(title)}</title>'
        f"<link>https://flowpulse.local/monitors</link>"
        f"<description>心流 FlowPulse · 监控作品聚合</description>"
        + "".join(items)
        + "</channel></rss>"
    )


def get_rss_repositories():
    """返回 (xhs_repo, douyin_repo, ks_repo, tiktok_repo)；由 runtime override 注入。"""
    raise RuntimeError("Dependency override is not configured")


@router.get("/monitors.xml")
def monitors_rss(
    platform: str = "",
    monitor_id: int | None = None,
    repos=Depends(get_rss_repositories),
) -> Response:
    xhs_repo, douyin_repo, ks_repo, tiktok_repo = repos
    platform_labels = {"xhs": "小红书", "douyin": "抖音", "ks": "快手", "tiktok": "TikTok"}

    all_entries: list[dict] = []
    sources = {
        "xhs": xhs_repo,
        "douyin": douyin_repo,
        "ks": ks_repo,
        "tiktok": tiktok_repo,
    }
    for pid, repo in sources.items():
        if repo is None:
            continue
        if platform and platform != pid:
            continue
        monitors = {m["id"]: (m.get("name") or m["target"]) for m in repo.list_monitors()}
        rows, _ = repo.list_contents(
            monitor_id=monitor_id if monitor_id is not None else None,
            page=1,
            page_size=_FEED_LIMIT,
        )
        for row in rows:
            row = dict(row)
            row["platform"] = pid
            row["monitor_name"] = row.get("monitor_name") or monitors.get(row.get("monitor_id"), "")
            all_entries.append(row)

    all_entries.sort(key=_entry_time, reverse=True)
    all_entries = all_entries[:_FEED_LIMIT]

    scope = platform_labels.get(platform, "全部平台") if platform else "全部平台"
    title = f"心流 FlowPulse · 作品监控（{scope}）"
    xml = build_monitor_rss(all_entries, title)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
