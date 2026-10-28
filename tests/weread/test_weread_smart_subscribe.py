"""智能订阅测试：文章链接识别公众号名称 → 搜索解析 bookId（含降级引导）。"""

import asyncio
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.weread.client import WereadAPIError, WereadClient
from flowpulse.modules.weread.models import MpArticle, MpSubscription
from flowpulse.modules.weread.service import NeedWereadLinkError, WereadService
from flowpulse.modules.weread.storage import WereadRepository

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


# ---- App 分享链接 hex 解码 ----


def test_normalize_decodes_app_share_link():
    """手机 App「⋯→复制链接」产出的 book-detail 链接：bookId hex 藏在 v 参数里。"""
    from flowpulse.modules.weread.models import normalize_book_id

    link = (
        "https://weread.qq.com/book-detail?type=1&senderVid=257969644"
        "&v=1914242224d505f5758535f33303139373437313136b34"
    )
    assert normalize_book_id(link) == "MP_WXS_3019747116"


# ---- 文章页名称提取 ----


@respx.mock
def test_fetch_article_account_extracts_name():
    async def run() -> None:
        respx.get("https://mp.weixin.qq.com/s/abc").respond(
            text='<html><body><strong id="js_name">孟健AI编程</strong></body></html>'
        )
        client = WereadClient(httpx.AsyncClient(), lambda: "", 0)
        account = await client.fetch_article_account("https://mp.weixin.qq.com/s/abc")
        assert account["name"] == "孟健AI编程"
        await client._client.aclose()

    asyncio.run(run())


@respx.mock
def test_fetch_article_account_from_js_var():
    async def run() -> None:
        respx.get("https://mp.weixin.qq.com/s/jsvar").respond(
            text='<html><head><script>var nickname = "开福发布";</script></head></html>'
        )
        client = WereadClient(httpx.AsyncClient(), lambda: "", 0)
        account = await client.fetch_article_account("https://mp.weixin.qq.com/s/jsvar")
        assert account["name"] == "开福发布"
        await client._client.aclose()

    asyncio.run(run())


# ---- service：搜索降级 / 命中 ----


def build_service(tmp_path: Path) -> tuple[WereadService, WereadRepository]:
    repository = WereadRepository(tmp_path)
    repository.save_credential("wr_vid=1; wr_skey=x")
    service = WereadService(repository, httpx.AsyncClient(), request_interval_seconds=0)
    return service, repository


def test_article_link_degrades_to_wizard(tmp_path: Path, monkeypatch):
    """文章链接 → 名称提取成功，但微信读书搜索不可用 → NeedWereadLinkError 引导。"""

    async def run() -> None:
        service, _ = build_service(tmp_path)

        async def fake_account(link):
            return {"name": "孟健AI编程"}

        async def fake_search(word):
            raise WereadAPIError("auth", -2012, "Cookie 已失效，请重新粘贴")

        monkeypatch.setattr(service.client, "fetch_article_account", fake_account)
        monkeypatch.setattr(service.client, "search_accounts", fake_search)

        with pytest.raises(NeedWereadLinkError) as exc:
            await service.add_subscription("https://mp.weixin.qq.com/s/abc")
        assert exc.value.name == "孟健AI编程"
        await service.client._client.aclose()

    asyncio.run(run())


def test_name_input_resolves_via_search(tmp_path: Path, monkeypatch):
    """直接输入公众号名称：搜索精确命中 → 自动完成订阅（含 cover 反查）。"""

    async def run() -> None:
        service, repository = build_service(tmp_path)

        async def fake_search(word):
            return [{"book_id": BOOK_ID, "title": "开福发布"}]

        async def fake_cover(book_id):
            return (
                MpArticle(review_id=f"{book_id}_c1", book_id=book_id, title="首篇"),
                {"name": "开福发布", "avatar": ""},
            )

        monkeypatch.setattr(service.client, "search_accounts", fake_search)
        monkeypatch.setattr(service.client, "fetch_cover", fake_cover)

        sub = await service.add_subscription("开福发布")
        assert sub.book_id == BOOK_ID
        assert repository.get_subscription(BOOK_ID).name == "开福发布"
        await service.client._client.aclose()

    asyncio.run(run())


# ---- API：422 结构化返回 ----


@respx.mock
def test_api_returns_wizard_payload(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": []})
    respx.get("https://mp.weixin.qq.com/s/x").respond(
        text='<html><body><strong id="js_name">孟健AI编程</strong></body></html>'
    )
    respx.get(f"{WEREAD}/web/search/global").respond(json={"errCode": -2012})

    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        response = client.post(
            "/api/weread/subscriptions", json={"input": "https://mp.weixin.qq.com/s/x"}
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "need_weread_link"
        assert detail["name"] == "孟健AI编程"
