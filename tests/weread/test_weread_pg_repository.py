"""PG 仓储全接口对等测试（sqlite 驱动，覆盖与文件仓储相同的行为契约）。

对齐 tests/weread/test_weread_hardening.py 中文件版的关键行为：
加密落库、明文兼容、密钥不符、订阅删除级联、排序兜底、状态 kv。
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from flowpulse.db.engine import ensure_tables
from flowpulse.db.models import WereadCredentialRow
from flowpulse.modules.weread.models import MpArticle, MpArticleContent, MpSubscription
from flowpulse.modules.weread.pg_repository import PgWereadRepository

BOOK_ID = "MP_WXS_3012726261"


def make_repo(tmp_path: Path, credential_key: str = "") -> PgWereadRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/db.sqlite", future=True)
    ensure_tables(engine)
    return PgWereadRepository(
        sessionmaker(bind=engine, expire_on_commit=False, future=True),
        credential_key=credential_key,
        key_file=tmp_path / ".credential_key",
    )


def test_credential_encrypted_at_rest(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.save_credential("wr_vid=123; wr_skey=abc")
    assert repo.get_credential().cookie == "wr_vid=123; wr_skey=abc"

    engine = create_engine(f"sqlite:///{tmp_path}/db.sqlite", future=True)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT cookie, cookie_encrypted FROM weread_credentials")).one()
    assert row.cookie_encrypted == 1
    assert "wr_skey=abc" not in row.cookie
    assert row.cookie.startswith("gAAA")


def test_credential_wrong_key_returns_none(tmp_path: Path):
    from cryptography.fernet import Fernet

    repo_a = make_repo(tmp_path, credential_key=Fernet.generate_key().decode())
    repo_a.save_credential("wr_vid=1; wr_skey=x")

    repo_b = make_repo(tmp_path, credential_key=Fernet.generate_key().decode())
    assert repo_b.get_credential() is None

    engine = create_engine(f"sqlite:///{tmp_path}/db.sqlite", future=True)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM weread_credentials")).one()
    assert row.id == 1  # 单行约束


def test_credential_delete(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.save_credential("wr_vid=1")
    assert repo.delete_credential() is True
    assert repo.get_credential() is None
    assert repo.delete_credential() is False


def test_subscription_crud_and_cascade(tmp_path: Path):
    repo = make_repo(tmp_path)
    review_id = f"{BOOK_ID}_abc"
    repo.upsert_subscription(MpSubscription(book_id=BOOK_ID, name="测试"))
    repo.upsert_articles(
        BOOK_ID, [MpArticle(review_id=review_id, book_id=BOOK_ID, title="文章")]
    )
    repo.save_content(
        MpArticleContent(review_id=review_id, book_id=BOOK_ID, content_html="<p>x</p>")
    )

    sub = repo.get_subscription(BOOK_ID)
    assert sub.name == "测试" and sub.article_count == 1
    assert repo.article_count(BOOK_ID) == 1

    # 删除订阅 → 文章与正文级联清理（对齐文件版行为）
    assert repo.delete_subscription(BOOK_ID) is True
    assert repo.get_subscription(BOOK_ID) is None
    assert repo.list_articles(BOOK_ID) == []
    assert repo.get_content(review_id) is None
    assert repo.delete_subscription(BOOK_ID) is False


def test_articles_dedup_sort_and_backfills(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.upsert_subscription(MpSubscription(book_id=BOOK_ID))

    old = MpArticle(
        review_id="r_old", book_id=BOOK_ID, publish_time=1000,
        created_at="2026-10-01T00:00:00+00:00",
    )
    fresh = MpArticle(
        review_id="r_new", book_id=BOOK_ID, publish_time=0,
        created_at="2026-10-27T00:00:00+00:00",
    )
    assert repo.upsert_articles(BOOK_ID, [old, fresh]) == 2
    assert repo.upsert_articles(BOOK_ID, [fresh]) == 0  # reviewId 去重

    articles = repo.list_articles(BOOK_ID)
    assert articles[0].review_id == "r_new"  # 0 时间按入库时间兜底，最新在前

    assert repo.set_article_publish_time(BOOK_ID, "r_new", 1793095122) is True
    assert repo.set_article_publish_time(BOOK_ID, "r_new", 1793095122) is False  # 无变化
    assert repo.set_article_digest(BOOK_ID, "r_new", "摘要内容") is True
    assert repo.set_article_digest(BOOK_ID, "r_new", "  ") is False  # 空摘要拒绝

    article = repo.list_articles(BOOK_ID)[0]
    assert article.publish_time == 1793095122 and article.digest == "摘要内容"


def test_content_upsert_overwrites(tmp_path: Path):
    repo = make_repo(tmp_path)
    rid = f"{BOOK_ID}_c1"
    repo.upsert_subscription(MpSubscription(book_id=BOOK_ID))
    repo.upsert_articles(BOOK_ID, [MpArticle(review_id=rid, book_id=BOOK_ID)])
    repo.save_content(MpArticleContent(review_id=rid, book_id=BOOK_ID, content_html="<p>v1</p>"))
    saved = repo.save_content(
        MpArticleContent(review_id=rid, book_id=BOOK_ID, content_html="<p>v2</p>", publish_time=123)
    )
    assert saved.content_html == "<p>v2</p>"
    cached = repo.get_content(rid)
    assert cached.content_html == "<p>v2</p>" and cached.publish_time == 123


def test_kv_states_roundtrip(tmp_path: Path):
    repo = make_repo(tmp_path)
    assert repo.load_scheduler_state()["enabled"] is False  # 默认值

    state = {"enabled": True, "interval_minutes": 120, "last_run_at": "2026-10-28T00:00:00+00:00"}
    repo.save_scheduler_state(state)
    assert repo.load_scheduler_state() == state

    refresher = {"enabled": True, "interval_hours": 24, "last_run_at": None}
    repo.save_cookie_refresher_state(refresher)
    assert repo.load_cookie_refresher_state()["interval_hours"] == 24


def test_refresh_subscription_stats(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.upsert_subscription(MpSubscription(book_id=BOOK_ID, name="测试"))
    repo.upsert_articles(
        BOOK_ID, [MpArticle(review_id=f"{BOOK_ID}_x", book_id=BOOK_ID)]
    )
    updated = repo.refresh_subscription_stats(BOOK_ID, "ok", "（cover 增量）")
    assert updated.last_sync_status == "ok"
    assert updated.last_error == "（cover 增量）"
    assert updated.last_sync_at is not None
    assert updated.article_count == 1
    # 时间可解析且接近现在（tz 处理正确性）
    parsed = datetime.fromisoformat(updated.last_sync_at)
    assert abs(parsed - datetime.now(timezone.utc)) < timedelta(minutes=1)
