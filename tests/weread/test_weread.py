"""微信读书采集模块测试：链接推导、存储去重、API 流程（respx mock）。"""

from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient

from metacorpus.config import Settings
from metacorpus.main import create_app
from weread.client import build_mp_url, link_from_review_id, parse_articles_payload
from weread.models import MpArticle
from weread.storage import WereadRepository

WEREAD = "https://weread.qq.com"
BOOK_ID = "MP_WXS_3012726261"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_request_interval_seconds=0,
    )


# ---- 纯逻辑 ----


def test_token_tilde_restored_in_link():
    assert build_mp_url("ySsAk3lUFT0Wh~9IZCtr-g") == (
        "https://mp.weixin.qq.com/s/ySsAk3lUFT0Wh_9IZCtr-g"
    )


def test_link_from_review_id_strips_book_prefix():
    assert link_from_review_id(f"{BOOK_ID}_LEbHjoebXuqJ4Psyh3-WQA", BOOK_ID) == (
        "https://mp.weixin.qq.com/s/LEbHjoebXuqJ4Psyh3-WQA"
    )


def test_parse_articles_payload():
    payload = {
        "reviews": [
            {
                "createTime": 1761549000,
                "subReviews": [
                    {
                        "review": {
                            "reviewId": f"{BOOK_ID}_r1~x",
                            "createTime": 1761549000,
                            "mpInfo": {
                                "title": "标题一",
                                "originalId": "r1~x",
                                "pic_url": "http://c/1.jpg",
                                "content": "摘要",
                                "time": 1761549000,
                            },
                        }
                    }
                ],
            }
        ]
    }
    articles = parse_articles_payload(payload, BOOK_ID)
    assert len(articles) == 1
    assert articles[0].link == "https://mp.weixin.qq.com/s/r1_x"
    assert articles[0].title == "标题一"


def test_repository_upsert_dedup(tmp_path: Path):
    repo = WereadRepository(tmp_path)
    article = MpArticle(review_id="r1", book_id=BOOK_ID, title="t")
    assert repo.upsert_articles(BOOK_ID, [article]) == 1
    assert repo.upsert_articles(BOOK_ID, [article]) == 0
    assert repo.article_count(BOOK_ID) == 1


# ---- API 流程 ----


@respx.mock
def test_credential_and_subscription_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": [{"bookId": "1"}, {"bookId": "2"}]})
    respx.get(f"{WEREAD}/api/mp/cover").respond(
        json={
            "name": "开福发布",
            "avatar": "http://x/avatar.png",
            "reviewId": f"{BOOK_ID}_LEbHjoebXuqJ4Psyh3~WQA",
            "title": "最新一篇",
            "pic": "http://x/pic.jpg",
        }
    )

    with TestClient(create_app()) as client:
        # 未配置凭证时的状态
        assert client.get("/api/weread/credential").json() == {"configured": False}

        # 保存并校验凭证
        response = client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        assert response.status_code == 200
        assert response.json() == {"valid": True, "message": "Cookie 有效", "book_count": 2}

        status = client.get("/api/weread/credential").json()
        assert status["configured"] is True
        assert status["valid"] is True

        # 添加订阅（粘贴链接形态的输入）
        response = client.post(
            "/api/weread/subscriptions",
            json={"input": "https://weread.qq.com/web/mp/reader/MP_WXS_3012726261"},
        )
        assert response.status_code == 201
        sub = response.json()
        assert sub["book_id"] == BOOK_ID
        assert sub["name"] == "开福发布"

        # cover 的最新一篇已入库，且 `~` 已还原
        response = client.get(f"/api/weread/subscriptions/{BOOK_ID}/articles")
        body = response.json()
        assert body["count"] == 1
        assert body["items"][0]["link"] == "https://mp.weixin.qq.com/s/LEbHjoebXuqJ4Psyh3_WQA"

        # 总览
        status = client.get("/api/weread/status").json()
        assert status["credential"]["valid"] is True
        assert status["subscriptions"][0]["article_count"] == 1


@respx.mock
def test_sync_dedup(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": []})
    respx.get(f"{WEREAD}/api/mp/cover").respond(
        json={"name": "测试号", "reviewId": f"{BOOK_ID}_cover1", "title": "t", "pic": "", "avatar": ""}
    )
    articles_payload = {
        "reviews": [
            {
                "createTime": 1761549000,
                "subReviews": [
                    {
                        "review": {
                            "reviewId": f"{BOOK_ID}_r1~x",
                            "createTime": 1761549000,
                            "mpInfo": {"title": "一", "originalId": "r1~x", "time": 1761549000},
                        }
                    },
                    {
                        "review": {
                            "reviewId": f"{BOOK_ID}_r2",
                            "createTime": 1761548000,
                            "mpInfo": {"title": "二", "originalId": "r2", "time": 1761548000},
                        }
                    },
                ],
            }
        ]
    }
    respx.get(f"{WEREAD}/web/mp/articles").respond(json=articles_payload)

    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        client.post("/api/weread/subscriptions", json={"input": BOOK_ID})

        summary = client.post("/api/weread/sync").json()
        assert summary["ok_count"] == 1
        assert summary["new_articles"] == 2

        # 再同步一次：reviewId 去重，不再新增
        summary = client.post("/api/weread/sync").json()
        assert summary["new_articles"] == 0
        assert summary["details"][0]["total_articles"] == 3  # cover 1 篇 + 列表 2 篇


@respx.mock
def test_articles_auth_error_falls_back_to_cover(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"books": []})
    cover_route = respx.get(f"{WEREAD}/api/mp/cover").respond(
        json={"name": "测试号", "reviewId": f"{BOOK_ID}_c1", "title": "t", "pic": "", "avatar": ""}
    )
    # 列表接口返回 -2041（部分账号已废弃）→ 应回退 cover
    respx.get(f"{WEREAD}/web/mp/articles").respond(json={"errCode": -2041, "errMsg": "expired"})

    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        client.post("/api/weread/subscriptions", json={"input": BOOK_ID})

        result = client.post(f"/api/weread/subscriptions/{BOOK_ID}/sync").json()
        assert result["status"] == "ok"
        assert result["new_articles"] == 0  # cover 那篇已在添加订阅时入库
        assert "cover" in result["message"]
        assert cover_route.called


def test_add_subscription_rejects_bad_input(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    with TestClient(create_app()) as client:
        response = client.post("/api/weread/subscriptions", json={"input": "随便什么"})
        assert response.status_code == 400


@respx.mock
def test_auth_error_maps_to_401(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    respx.get(f"{WEREAD}/web/shelf/sync").respond(json={"errCode": -2012, "errMsg": "timeout"})

    with TestClient(create_app()) as client:
        response = client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        assert response.status_code == 200
        assert response.json()["valid"] is False
        assert response.json()["message"] == "Cookie 已失效，请重新粘贴"

        # 凭证无效时添加订阅 → 401
        respx.get(f"{WEREAD}/api/mp/cover").respond(
            json={"errCode": -2012, "errMsg": "timeout"}
        )
        response = client.post("/api/weread/subscriptions", json={"input": BOOK_ID})
        assert response.status_code == 401


@respx.mock
def test_validate_falls_back_to_cover_when_shelf_restricted(tmp_path: Path, monkeypatch):
    """书架接口比 cover 严格：书架 -2012 但 cover 可用时，凭证应判为有效。"""
    monkeypatch.setattr("metacorpus.main.get_settings", lambda: make_settings(tmp_path))
    # 第一次 shelf（保存凭证时校验）：无订阅阶段，返回空书架
    shelf_route = respx.get(f"{WEREAD}/web/shelf/sync")
    shelf_route.side_effect = [
        httpx.Response(200, json={"books": []}),  # 保存凭证时：通过
        httpx.Response(200, json={"errCode": -2012, "errMsg": "timeout"}),  # 复验时：受限
    ]
    respx.get(f"{WEREAD}/api/mp/cover").respond(
        json={"name": "测试号", "reviewId": f"{BOOK_ID}_c1", "title": "t", "pic": "", "avatar": ""}
    )

    with TestClient(create_app()) as client:
        client.post("/api/weread/credential", json={"cookie": "wr_vid=1; wr_skey=x"})
        client.post("/api/weread/subscriptions", json={"input": BOOK_ID})

        response = client.post("/api/weread/credential/validate")
        body = response.json()
        assert body["valid"] is True
        assert "cover" in body["message"]

        status = client.get("/api/weread/credential").json()
        assert status["valid"] is True
