"""二轮加固测试：自愈续期、删凭证清 profile、启动补跑、排序兜底、摘要回填、抓取上限。"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from metacorpus.config import Settings
from metacorpus.main import create_app
from weread.client import WereadAPIError, WereadClient
from weread.models import MpArticle, MpSubscription, now_iso
from weread.refresh import WereadCookieRefresher
from weread.scheduler import WereadScheduler
from weread.service import WereadService
from weread.storage import WereadRepository

WEREAD = "https://weread.qq.com"
BOOK_ID = "MP_WXS_3012726261"


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_request_interval_seconds=0,
        weread_sync_interval_minutes=0,
        weread_webhook_url="",
        weread_cookie_refresh_hours=0,
    )
    defaults.update(overrides)
    return Settings(**defaults)


class FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, key: str, title: str, message: str, cooldown_seconds: int = 3600) -> bool:
        self.sent.append(key)
        return True


# ---- A4 排序兜底 ----


def test_article_sort_zero_time_uses_created_at(tmp_path: Path):
    """未回填时间的最新文章应排在已有发布时间的旧文章之前，而不是沉底。"""
    repo = WereadRepository(tmp_path)
    old = MpArticle(
        review_id="r_old", book_id=BOOK_ID, publish_time=1000,
        created_at="2026-10-01T00:00:00+00:00",
    )
    fresh = MpArticle(
        review_id="r_new", book_id=BOOK_ID, publish_time=0,
        created_at="2026-10-27T00:00:00+00:00",
    )
    repo.upsert_articles(BOOK_ID, [old, fresh])
    articles = repo.list_articles(BOOK_ID)
    assert articles[0].review_id == "r_new"


# ---- A1 删凭证清 profile ----


@respx.mock
def test_delete_credential_clears_browser_profile(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": []})
    profile = tmp_path / "weread" / "browser_profile"
    profile.mkdir(parents=True)
    (profile / "Preferences").write_text("{}", encoding="utf-8")

    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        body = client.delete("/api/weread/credential").json()
        assert body["deleted"] is True
        assert body["profile_cleared"] is True
        assert not profile.exists()  # 登录态不残留，续期无法"复活"凭证
        assert client.get("/api/weread/credential").json()["configured"] is False


def test_refresh_skips_silently_without_credential(tmp_path: Path):
    """凭证被主动删除后（profile 一并清除）：续期静默跳过，不告警不打扰。"""
    import types

    class EmptyProfileManager:
        async def capture_cookie_headless(self) -> str:
            return ""

    notifier = FakeNotifier()
    refresher = WereadCookieRefresher(
        EmptyProfileManager(), types.SimpleNamespace(), WereadRepository(tmp_path),
        notifier=notifier, interval_hours=24,
    )
    result = asyncio.run(refresher.run_once())
    assert result["reason"] == "no_credential"
    assert notifier.sent == []


# ---- A2 浏览器异常不 500 ----


def test_refresh_maps_any_browser_exception(tmp_path: Path):
    import types

    class BrokenManager:
        async def capture_cookie_headless(self) -> str:
            raise TimeoutError("page.goto 超时")  # 非 RuntimeError，此前会裸抛

    refresher = WereadCookieRefresher(
        BrokenManager(), types.SimpleNamespace(), WereadRepository(tmp_path), interval_hours=24
    )
    result = asyncio.run(refresher.run_once())
    assert result["ok"] is False
    assert result["reason"] == "browser_error"


# ---- A3 启动补跑 ----


def test_scheduler_catches_up_when_overdue(tmp_path: Path):
    repo = WereadRepository(tmp_path)
    scheduler = WereadScheduler(object(), repo, interval_minutes=120)
    # 从未跑过：等满一个周期
    assert scheduler._seconds_until_due() == 120 * 60

    stale = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
    repo.save_scheduler_state({"enabled": True, "interval_minutes": 120,
                               "running": False, "last_run_at": stale, "last_result": None})
    assert scheduler._seconds_until_due() == 0  # 已超期：立即补跑


def test_refresher_catches_up_when_overdue(tmp_path: Path):
    import types

    repo = WereadRepository(tmp_path)
    refresher = WereadCookieRefresher(
        types.SimpleNamespace(), types.SimpleNamespace(), repo, interval_hours=24
    )
    assert refresher._seconds_until_due() == 24 * 3600

    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec="seconds")
    repo.save_cookie_refresher_state({"enabled": True, "interval_hours": 24,
                                      "running": False, "last_run_at": stale, "last_result": None})
    assert refresher._seconds_until_due() == 0


# ---- B5 失效自愈 ----


def test_sync_self_heals_then_recovers(tmp_path: Path, monkeypatch):
    async def run() -> None:
        repo = WereadRepository(tmp_path)
        repo.save_credential("old_cookie")
        repo.upsert_subscription(MpSubscription(book_id=BOOK_ID, name="测试"))
        service = WereadService(repo, httpx.AsyncClient(), request_interval_seconds=0)

        cover_calls = {"n": 0}

        async def fake_articles(book_id, offset=0):
            raise WereadAPIError("auth", -2012, "Cookie 已失效")

        async def fake_cover(book_id):
            cover_calls["n"] += 1
            if cover_calls["n"] == 1:
                raise WereadAPIError("auth", -2012, "Cookie 已失效")
            return MpArticle(review_id=f"{book_id}_c9", book_id=book_id, title="新文章"), {}

        monkeypatch.setattr(service.client, "fetch_articles", fake_articles)
        monkeypatch.setattr(service.client, "fetch_cover", fake_cover)

        heals = {"n": 0}

        async def fake_heal():
            heals["n"] += 1
            return {"ok": True, "message": "Cookie 有效"}

        service.attach_self_heal(fake_heal)

        result = await service.sync_subscription(BOOK_ID)
        assert result.status == "ok"
        assert "自动续期" in result.message
        assert heals["n"] == 1
        assert cover_calls["n"] == 2  # 失败一次 → 续期 → 重试成功

        await service.client._client.aclose()

    asyncio.run(run())


def test_self_heal_cooldown_prevents_repeat(tmp_path: Path, monkeypatch):
    async def run() -> None:
        repo = WereadRepository(tmp_path)
        repo.save_credential("old_cookie")
        repo.upsert_subscription(MpSubscription(book_id=BOOK_ID, name="测试"))
        service = WereadService(repo, httpx.AsyncClient(), request_interval_seconds=0)

        async def fake_articles(book_id, offset=0):
            raise WereadAPIError("auth", -2012, "Cookie 已失效")

        async def fake_cover(book_id):
            raise WereadAPIError("auth", -2012, "Cookie 已失效")  # 续期也救不回来

        monkeypatch.setattr(service.client, "fetch_articles", fake_articles)
        monkeypatch.setattr(service.client, "fetch_cover", fake_cover)

        heals = {"n": 0}

        async def fake_heal():
            heals["n"] += 1
            return {"ok": True}

        service.attach_self_heal(fake_heal)

        first = await service.sync_subscription(BOOK_ID)
        second = await service.sync_subscription(BOOK_ID)
        assert first.status == "auth_error" and second.status == "auth_error"
        assert heals["n"] == 1  # 冷却期内不重复拉起浏览器

        await service.client._client.aclose()

    asyncio.run(run())


# ---- B6 摘要回填 / B7 抓取上限 ----


@respx.mock
def test_digest_backfilled_after_content_fetch(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": []})
    respx.get(f"{WEREAD}/api/mp/cover").respond(
        json={"name": "测试号", "reviewId": f"{BOOK_ID}_d1", "title": "摘要篇", "pic": "", "avatar": ""}
    )
    respx.get("https://mp.weixin.qq.com/s/d1").respond(
        text='<html><head><script>var ct = "1793095122";</script></head>'
             '<body><div id="js_content"><p>这是用来验证摘要回填的第一段正文内容，足够长以供截断。</p></div></body></html>'
    )
    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        client.post("/api/weread/subscriptions", json={"input": BOOK_ID})
        review_id = client.get(f"/api/weread/subscriptions/{BOOK_ID}/articles").json()["items"][0]["review_id"]
        assert client.get(f"/api/weread/articles/{BOOK_ID}/{review_id}/content").status_code == 200

        item = client.get(f"/api/weread/subscriptions/{BOOK_ID}/articles").json()["items"][0]
        assert item["digest"].startswith("这是用来验证摘要回填")
        # RSS 条目带上 description
        xml = client.get(f"/api/weread/rss/{BOOK_ID}.xml").text
        assert "<description>" in xml


@respx.mock
def test_public_page_size_cap(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("weread.client.PUBLIC_PAGE_MAX_BYTES", 32)
    async def run() -> None:
        client = WereadClient(httpx.AsyncClient(), lambda: "", 0)
        respx.get("https://mp.weixin.qq.com/s/big").respond(
            text="<html>" + "x" * 200 + "</html>"
        )
        with pytest.raises(WereadAPIError) as exc:
            await client.fetch_public_article("https://mp.weixin.qq.com/s/big")
        assert exc.value.code == "too_large"
        await client._client.aclose()

    asyncio.run(run())
