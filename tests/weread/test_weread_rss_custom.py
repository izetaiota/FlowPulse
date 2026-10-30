"""RSS 订阅定制、正文清洗、新文章推送与多渠道通知测试。"""

import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.core.notify import WebhookNotifier
from flowpulse.main import create_app
from flowpulse.modules.weread.clean import clean_html
from flowpulse.modules.weread.models import (
    MpArticle,
    MpArticleContent,
    MpSubscription,
    SubscriptionUpdateRequest,
)
from flowpulse.modules.weread.service import WereadService
from flowpulse.modules.weread.storage import WereadRepository

BOOK_ID = "MP_WXS_3012726261"


# ---- 正文清洗 ----


def test_clean_html_default_rules():
    html = (
        "<p>正文段落</p>"
        '<section class="qr_code_pc_outer"><img src="qr.png"/></section>'
        '<div id="reward_area">赞赏内容</div>'
        "<p>结尾</p>"
    )
    cleaned = clean_html(html)
    assert "正文段落" in cleaned and "结尾" in cleaned
    assert "qr.png" not in cleaned and "赞赏内容" not in cleaned


def test_clean_html_extra_keywords_and_nesting():
    html = (
        '<div class="content"><p>保留</p>'
        '<section class="promo_banner"><div><span>广告</span></div></section>'
        "</div>"
    )
    cleaned = clean_html(html, "promo_banner")
    assert "保留" in cleaned and "广告" not in cleaned and "promo_banner" not in cleaned


def test_clean_html_keeps_entities_and_void():
    html = '<p class="keep">A &amp; B<br/><img src="x.jpg"/></p>'
    assert clean_html(html) == html


# ---- 多渠道通知 ----


def test_notifier_multichannel_dedupe_and_formats():
    feishu_url = "https://open.feishu.cn/open-apis/bot/v2/hook/a"
    notifier = WebhookNotifier(None, f" {feishu_url} , {feishu_url} , ")
    assert notifier._all_urls() == [feishu_url]  # 去重去空
    payload = notifier._payload(feishu_url, "标题", "内容")
    assert payload == {"msg_type": "text", "content": {"text": "标题\n内容"}}

    image_payload = notifier._image_payload(feishu_url, "t", "m", "aGVsbG8=")
    assert image_payload["msg_type"] == "image"
    assert set(image_payload["image"]) == {"base64", "md5"}


# ---- 订阅编辑 + RSS 定制 ----


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_request_interval_seconds=0,
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
        admin_password="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _seed_articles(repo: WereadRepository, count: int = 3) -> None:
    for i in range(count):
        review_id = f"r{i}"
        repo.upsert_articles(
            BOOK_ID,
            [MpArticle(review_id=review_id, book_id=BOOK_ID, title=f"文章{i}",
                       link=f"https://mp.weixin.qq.com/s/{review_id}")],
        )
        repo.save_content(
            MpArticleContent(
                review_id=review_id,
                book_id=BOOK_ID,
                title=f"文章{i}",
                content_html=f"<p>正文{i}</p>"
                + ('<section class="qr_code_pc_outer">二维码</section>' if i == 0 else ""),
            )
        )


def test_subscription_update_and_rss_customization(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path, weread_rss_full_text=False)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        repo = WereadRepository(tmp_path)
        repo.upsert_subscription(MpSubscription(book_id=BOOK_ID, name="码农翻身"))
        _seed_articles(repo)

        # 编辑订阅：自定义标题/描述/每订阅全文/条数
        updated = client.put(
            f"/api/weread/subscriptions/{BOOK_ID}",
            json={
                "name": "码农翻身",
                "rss_title": "我的技术周刊",
                "rss_description": "只看硬核文章",
                "rss_full_text": True,
                "rss_max_items": 2,
                "strip_keywords": "",
                "notify_new": True,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["rss_title"] == "我的技术周刊"

        xml = client.get(f"/api/weread/rss/{BOOK_ID}.xml").text
        # 标题/描述定制生效；条数上限 2；订阅级全文覆盖全局 False；默认清洗去掉二维码块
        assert "我的技术周刊" in xml and "只看硬核文章" in xml
        assert xml.count("<item>") == 2
        assert "content:encoded" in xml and "正文" in xml
        assert "二维码" not in xml and "qr_code_pc_outer" not in xml

        # rss_full_text 恢复跟随全局（null）后不再输出全文
        client.put(
            f"/api/weread/subscriptions/{BOOK_ID}",
            json={"name": "码农翻身", "rss_full_text": None},
        )
        xml = client.get(f"/api/weread/rss/{BOOK_ID}.xml").text
        assert "content:encoded" not in xml

        assert client.put(
            "/api/weread/subscriptions/MP_WXS_404", json={"name": "x"}
        ).status_code == 404


def test_update_subscription_preserves_sync_state(tmp_path: Path):
    repo = WereadRepository(tmp_path)
    sub = MpSubscription(book_id=BOOK_ID, name="旧名", last_sync_status="ok", article_count=9)
    repo.upsert_subscription(sub)
    service = WereadService(repo, httpx.AsyncClient(), request_interval_seconds=0)
    updated = service.update_subscription(
        BOOK_ID,
        SubscriptionUpdateRequest(name="新名", strip_keywords="ad, banner"),
    )
    assert updated.name == "新名" and updated.strip_keywords == "ad, banner"
    assert updated.last_sync_status == "ok"  # 同步状态不被编辑覆盖
    reloaded = repo.get_subscription(BOOK_ID)
    assert reloaded.name == "新名" and reloaded.last_sync_status == "ok"
    asyncio.run(service.client._client.aclose())


# ---- 新文章推送 ----


class FakeNotifier:
    def __init__(self):
        self.calls = []

    @property
    def configured(self):
        return True

    async def send(self, key, title, message, cooldown_seconds=3600):
        self.calls.append((key, title, message))
        return True


def test_new_articles_push_notification(tmp_path: Path, monkeypatch):
    async def run() -> None:
        repo = WereadRepository(tmp_path)
        repo.save_credential("cookie")
        repo.upsert_subscription(MpSubscription(book_id=BOOK_ID, name="码农翻身"))
        notifier = FakeNotifier()
        service = WereadService(
            repo, httpx.AsyncClient(), request_interval_seconds=0, notifier=notifier
        )

        article = MpArticle(
            review_id="new1", book_id=BOOK_ID, title="新文章",
            link="https://mp.weixin.qq.com/s/new1",
        )

        async def fake_articles(book_id, offset=0):
            return [article]

        monkeypatch.setattr(service.client, "fetch_articles", fake_articles)

        first = await service.sync_subscription(BOOK_ID)
        assert first.new_articles == 1 and len(notifier.calls) == 1
        key, title, message = notifier.calls[0]
        assert key == f"weread:new:{BOOK_ID}" and "1 篇" in title
        assert "新文章" in message and article.link in message

        # 第二次同步无新文章：不推送
        second = await service.sync_subscription(BOOK_ID)
        assert second.new_articles == 0 and len(notifier.calls) == 1

        await service.client._client.aclose()

    asyncio.run(run())


def test_push_disabled_by_subscription_flag(tmp_path: Path, monkeypatch):
    async def run() -> None:
        repo = WereadRepository(tmp_path)
        repo.save_credential("cookie")
        repo.upsert_subscription(
            MpSubscription(book_id=BOOK_ID, name="安静号", notify_new=False)
        )
        notifier = FakeNotifier()
        service = WereadService(
            repo, httpx.AsyncClient(), request_interval_seconds=0, notifier=notifier
        )

        async def fake_articles(book_id, offset=0):
            return [MpArticle(review_id="x1", book_id=BOOK_ID, title="t")]

        monkeypatch.setattr(service.client, "fetch_articles", fake_articles)
        result = await service.sync_subscription(BOOK_ID)
        assert result.new_articles == 1 and notifier.calls == []

        await service.client._client.aclose()

    asyncio.run(run())


# ---- 订阅级同步周期（scheduler tick 化） ----


def test_sub_level_sync_interval_due_check(tmp_path: Path):
    from datetime import UTC, datetime, timedelta

    from flowpulse.modules.weread.scheduler import WereadScheduler

    repo = WereadRepository(tmp_path)
    scheduler = WereadScheduler(
        WereadService(repo, httpx.AsyncClient(), request_interval_seconds=0),
        repo,
        interval_minutes=60,
    )
    now = datetime.now(UTC)

    fresh = MpSubscription(
        book_id="FRESH", last_sync_at=(now - timedelta(minutes=5)).isoformat()
    )  # 全局 60 分钟，5 分钟前同步过 → 未到期
    assert scheduler._sub_due(fresh) is False

    custom_short = MpSubscription(
        book_id="SHORT", sync_interval_minutes=30,
        last_sync_at=(now - timedelta(minutes=40)).isoformat(),
    )  # 订阅级 30 分钟，40 分钟前 → 到期
    assert scheduler._sub_due(custom_short) is True

    custom_long = MpSubscription(
        book_id="LONG", sync_interval_minutes=240,
        last_sync_at=(now - timedelta(minutes=100)).isoformat(),
    )  # 订阅级 240 分钟，100 分钟前 → 未到期（全局 60 不影响）
    assert scheduler._sub_due(custom_long) is False

    never = MpSubscription(book_id="NEVER")  # 从未同步 → 到期
    assert scheduler._sub_due(never) is True
