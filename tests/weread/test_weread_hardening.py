"""加固测试：Cookie 静态加密、订阅删除清理缓存、频率限制冷却。"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from weread.client import WereadAPIError, WereadClient
from weread.models import MpArticle, MpArticleContent, MpSubscription
from weread.storage import WereadRepository

WEREAD = "https://weread.qq.com"


# ---- Cookie 静态加密 ----


def test_credential_encrypted_at_rest(tmp_path: Path):
    repo = WereadRepository(tmp_path)
    repo.save_credential("wr_vid=123; wr_skey=abc")

    raw = json.loads((tmp_path / "weread" / "credential.json").read_text(encoding="utf-8"))
    assert raw["cookie_encrypted"] is True
    assert "wr_skey=abc" not in raw["cookie"]  # 落盘内容不含明文
    assert raw["cookie"].startswith("gAAA")

    # 读回自动解密
    assert repo.get_credential().cookie == "wr_vid=123; wr_skey=abc"


def test_credential_legacy_plaintext_still_readable(tmp_path: Path):
    """旧版明文文件可正常读取，下次保存自动升级为加密。"""
    target = tmp_path / "weread" / "credential.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"cookie": "wr_vid=1", "saved_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    repo = WereadRepository(tmp_path)
    credential = repo.get_credential()
    assert credential.cookie == "wr_vid=1"

    repo.update_credential(credential)
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert raw.get("cookie_encrypted") is True


def test_credential_unreadable_with_wrong_key(tmp_path: Path):
    """密钥与加密时不一致：凭证视为不可用（返回 None），不抛异常。"""
    from cryptography.fernet import Fernet

    key_a = Fernet.generate_key().decode()
    repo_a = WereadRepository(tmp_path, credential_key=key_a)
    repo_a.save_credential("wr_vid=1; wr_skey=x")

    key_b = Fernet.generate_key().decode()
    repo_b = WereadRepository(tmp_path, credential_key=key_b)
    assert repo_b.get_credential() is None


# ---- 订阅删除清理 ----


def test_delete_subscription_removes_articles_and_contents(tmp_path: Path):
    repo = WereadRepository(tmp_path)
    book_id = "MP_WXS_1"
    review_id = "MP_WXS_1_abc"
    repo.upsert_subscription(MpSubscription(book_id=book_id, name="测试"))
    repo.upsert_articles(book_id, [MpArticle(review_id=review_id, book_id=book_id)])
    repo.save_content(
        MpArticleContent(review_id=review_id, book_id=book_id, content_html="<p>x</p>")
    )
    assert (tmp_path / "weread" / "articles" / f"{book_id}.json").is_file()
    assert (tmp_path / "weread" / "contents" / f"{review_id}.json").is_file()

    assert repo.delete_subscription(book_id) is True
    assert not (tmp_path / "weread" / "articles" / f"{book_id}.json").exists()
    assert not (tmp_path / "weread" / "contents" / f"{review_id}.json").exists()


# ---- 频率限制冷却 ----


@respx.mock
def test_rate_limit_triggers_cooldown():
    """触发 200013 后进入冷却：后续请求直接抛错，不再发起 HTTP 调用。"""

    async def run() -> None:
        client = WereadClient(httpx.AsyncClient(), lambda: "wr_vid=1", 0)
        route = respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"errCode": 200013})

        with pytest.raises(WereadAPIError) as first:
            await client.fetch_shelf_books()
        assert first.value.kind == "rate_limit"

        with pytest.raises(WereadAPIError) as second:
            await client.fetch_shelf_books()
        assert "冷却" in second.value.message
        assert route.call_count == 1  # 第二次没有真正发请求

        await client._client.aclose()

    asyncio.run(run())
