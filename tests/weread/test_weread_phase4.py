"""阶段 4 测试：正文提取、按需抓取缓存、RSS 全文模式、发布时间回填。"""

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from metacorpus.config import Settings
from metacorpus.main import create_app
from weread.client import (
    WereadAPIError,
    extract_mp_content,
    extract_publish_time,
    harden_images,
)
from weread.models import MpArticle
from weread.rss import build_rss

WEREAD = "https://weread.qq.com"
BOOK_ID = "MP_WXS_3012726261"
REVIEW_ID = f"{BOOK_ID}_abc123"
PUBLIC_PAGE_WITH_TIME = (
    '<html><head><script>var ct = "1793095122";</script></head>'
    '<body><div id="js_content"><p>正文内容 ABC</p></div></body></html>'
)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_request_interval_seconds=0,
        weread_sync_interval_minutes=0,
        weread_webhook_url="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ---- 正文提取 ----


def test_extract_js_content_node():
    html = """
    <html><body>
    <div id="js_content"><p>第一段</p><script>evil()</script><p>第二段</p></div>
    </body></html>
    """
    content = extract_mp_content(html)
    assert "第一段" in content and "第二段" in content
    assert "script" not in content


def test_extract_resolves_lazyload_data_src():
    """微信图片懒加载：真实 URL 在 data-src，提取时需回填 src。"""
    html = (
        '<div id="js_content">'
        '<img data-src="https://mmbiz.qpic.cn/real.jpg" src=""/>'
        "</div>"
    )
    content = extract_mp_content(html)
    assert 'src="https://mmbiz.qpic.cn/real.jpg"' in content


def test_extract_content_noencode_fallback():
    """新版页面无 js_content，正文在 JS 变量 content_noencode（\\x0a 换行，内部引号转义）。"""
    html = "window.data = {content_noencode: '第一段\\x0a第二段\\'引用', next: 'v'};"
    content = extract_mp_content(html)
    assert "<p>第一段</p>" in content
    assert "<p>第二段'引用</p>" in content


def test_extract_raises_when_nothing_found():
    with pytest.raises(WereadAPIError):
        extract_mp_content("<html><body>啥也没有</body></html>")


def test_harden_images_adds_no_referrer():
    html = '<img src="https://mmbiz.qpic.cn/a.jpg"/><img referrerpolicy="no-referrer" src="b"/>'
    hardened = harden_images(html)
    assert hardened.count('referrerpolicy="no-referrer"') == 2


def test_extract_publish_time_variants():
    """公开页三种时间标记都能识别；识别不了/位数异常返回 0。"""
    assert extract_publish_time('<script>var ct = "1793095122";</script>') == 1793095122
    assert extract_publish_time("window.oriCreateTime = '1793095122'") == 1793095122
    assert extract_publish_time('{"create_time":"1793095122"}') == 1793095122
    assert extract_publish_time("<html>无时间标记</html>") == 0
    assert extract_publish_time('<script>var ct = "123";</script>') == 0


# ---- API：按需抓取并缓存 ----


@respx.mock
def test_article_content_fetch_and_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": []})
    respx.get(f"{WEREAD}/api/mp/cover").respond(
        json={"name": "测试号", "reviewId": f"{BOOK_ID}_c1", "title": "封面篇", "pic": "", "avatar": ""}
    )
    # 主路径：公开原文页（cover 生成的文章 reviewId 后缀 c1 → 链接 /s/c1），含 ct 时间标记
    public_route = respx.get("https://mp.weixin.qq.com/s/c1").respond(text=PUBLIC_PAGE_WITH_TIME)

    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        client.post("/api/weread/subscriptions", json={"input": BOOK_ID})
        review_id = client.get(f"/api/weread/subscriptions/{BOOK_ID}/articles").json()["items"][0]["review_id"]

        # 第一次：公开页抓取并缓存，同时提取发布时间
        response = client.get(f"/api/weread/articles/{BOOK_ID}/{review_id}/content")
        assert response.status_code == 200
        body = response.json()
        assert "正文内容 ABC" in body["content_html"]
        assert body["publish_time"] == 1793095122
        assert public_route.call_count == 1

        # 发布时间回填到文章记录（cover 通道本身没有时间）
        items = client.get(f"/api/weread/subscriptions/{BOOK_ID}/articles").json()["items"]
        assert items[0]["publish_time"] == 1793095122

        # 第二次：命中缓存（时间已知），不再请求
        response = client.get(f"/api/weread/articles/{BOOK_ID}/{review_id}/content")
        assert response.status_code == 200
        assert public_route.call_count == 1

        # 不存在的文章 → 404
        response = client.get(f"/api/weread/articles/{BOOK_ID}/MP_WXS_none/content")
        assert response.status_code == 404


@respx.mock
def test_article_content_refetch_when_cache_missing_time(tmp_path: Path, monkeypatch):
    """老缓存（无发布时间）会在下次阅读时补抓原文页一次，拿到时间后不再请求。"""
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": []})
    respx.get(f"{WEREAD}/api/mp/cover").respond(
        json={"name": "测试号", "reviewId": f"{BOOK_ID}_c1", "title": "封面篇", "pic": "", "avatar": ""}
    )
    no_time_page = '<html><body><div id="js_content"><p>旧版页面</p></div></body></html>'
    public_route = respx.get("https://mp.weixin.qq.com/s/c1")
    public_route.side_effect = [
        httpx.Response(200, text=no_time_page),
        httpx.Response(200, text=PUBLIC_PAGE_WITH_TIME),
    ]

    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        client.post("/api/weread/subscriptions", json={"input": BOOK_ID})
        review_id = client.get(f"/api/weread/subscriptions/{BOOK_ID}/articles").json()["items"][0]["review_id"]

        first = client.get(f"/api/weread/articles/{BOOK_ID}/{review_id}/content").json()
        assert first["publish_time"] == 0

        # 缓存缺时间 → 再抓一次原文页补时间
        second = client.get(f"/api/weread/articles/{BOOK_ID}/{review_id}/content").json()
        assert second["publish_time"] == 1793095122
        assert public_route.call_count == 2

        # 时间已知后彻底走缓存
        third = client.get(f"/api/weread/articles/{BOOK_ID}/{review_id}/content").json()
        assert third["publish_time"] == 1793095122
        assert public_route.call_count == 2
        items = client.get(f"/api/weread/subscriptions/{BOOK_ID}/articles").json()["items"]
        assert items[0]["publish_time"] == 1793095122


# ---- RSS 全文 ----


def test_rss_full_text_mode():
    articles = [MpArticle(review_id="r1", book_id=BOOK_ID, title="t", link="https://x")]
    xml = build_rss("标题", "http://x/", "描述", articles, contents={"r1": "<p>全文]]></p>"})
    assert 'xmlns:content="http://purl.org/rss/1.0/modules/content/"' in xml
    assert "<content:encoded><![CDATA[<p>全文]]]]><![CDATA[></p>]]></content:encoded>" in xml

    plain = build_rss("标题", "http://x/", "描述", articles)
    assert "content:encoded" not in plain
    assert "xmlns:content" not in plain
