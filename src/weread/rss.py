"""RSS 2.0 输出生成（手写 XML 模板，不引第三方依赖）。"""

from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from weread.models import MpArticle

_ATTR_ENTITIES = {'"': "&quot;", "'": "&apos;"}


def _pub_date(article: MpArticle) -> str | None:
    if article.publish_time > 0:
        return format_datetime(datetime.fromtimestamp(article.publish_time, tz=timezone.utc))
    try:
        parsed = datetime.fromisoformat(article.created_at)
        return format_datetime(parsed)
    except ValueError:
        return None


def build_rss(title: str, link: str, description: str, articles: list[MpArticle]) -> str:
    """生成 RSS 2.0 文档。文章应已按时间倒序排好。"""
    items: list[str] = []
    for article in articles:
        pub_date = _pub_date(article)
        item = [
            "<item>",
            f"<title>{escape(article.title or '(无标题)')}</title>",
            f"<link>{escape(article.link)}</link>",
            f"<guid isPermaLink=\"false\">{escape(article.review_id)}</guid>",
        ]
        if pub_date:
            item.append(f"<pubDate>{escape(pub_date)}</pubDate>")
        if article.digest:
            item.append(f"<description>{escape(article.digest)}</description>")
        if article.cover:
            escaped_cover = escape(article.cover, _ATTR_ENTITIES)
            item.append(
                f'<enclosure url="{escaped_cover}" type="image/jpeg" length="0"/>'
            )
        item.append("</item>")
        items.append("\n".join(item))

    now = format_datetime(datetime.now(timezone.utc))
    body = "\n".join(items)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>{escape(title)}</title>
<link>{escape(link)}</link>
<description>{escape(description)}</description>
<generator>FlowPulse WeRead</generator>
<lastBuildDate>{escape(now)}</lastBuildDate>
<ttl>120</ttl>
{body}
</channel>
</rss>
"""
