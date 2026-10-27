"""微信读书采集服务：凭证管理、订阅解析、增量同步。"""

from __future__ import annotations

import httpx

from weread.client import WereadAPIError, WereadClient
from weread.models import (
    MpSubscription,
    SubscriptionSyncResult,
    SyncSummary,
    normalize_book_id,
    now_iso,
)
from weread.storage import WereadRepository


class WereadService:
    def __init__(
        self,
        repository: WereadRepository,
        http_client: httpx.AsyncClient,
        request_interval_seconds: float = 2.0,
    ):
        self.repository = repository
        self.client = WereadClient(
            http_client,
            lambda: (credential.cookie if (credential := self.repository.get_credential()) else ""),
            request_interval_seconds,
        )

    def _require_credential(self) -> str:
        state = self.repository.get_credential()
        if not state or not state.cookie:
            raise WereadAPIError("auth", "no_cookie", "尚未配置微信读书 Cookie")
        return state.cookie

    # ---- 凭证 ----

    async def save_credential(self, cookie: str) -> dict:
        """保存 Cookie 并立即校验（拉一次书架）。"""
        state = self.repository.save_credential(cookie)
        result = await self._validate(state)
        return result

    async def validate_current_credential(self) -> dict:
        state = self.repository.get_credential()
        if not state:
            raise WereadAPIError("auth", "no_cookie", "尚未配置微信读书 Cookie")
        return await self._validate(state)

    async def _validate(self, state) -> dict:
        try:
            books = await self.client.fetch_shelf_books()
        except WereadAPIError as exc:
            # 书架接口比 cover 更严格：书架报登录失效时，若已有订阅，
            # 用第一个订阅的 cover 再探一次（采集通道仍可用则不算失效）
            subs = self.repository.list_subscriptions()
            if subs:
                try:
                    await self.client.fetch_cover(subs[0].book_id)
                except WereadAPIError:
                    pass
                else:
                    state.valid = True
                    state.last_validated_at = now_iso()
                    state.last_error = f"书架接口受限（{exc.message}），采集通道（cover）可用"
                    self.repository.update_credential(state)
                    return {"valid": True, "message": state.last_error, "book_count": 0}
            state.valid = False
            state.last_error = exc.message
            self.repository.update_credential(state)
            return {"valid": False, "message": exc.message, "book_count": 0}
        state.valid = True
        state.last_error = ""
        state.last_validated_at = now_iso()
        self.repository.update_credential(state)
        return {"valid": True, "message": "Cookie 有效", "book_count": len(books)}

    # ---- 订阅 ----

    async def add_subscription(self, raw_input: str) -> MpSubscription:
        """粘贴 bookId / 微信读书链接添加订阅，用 cover 接口反查名称头像。"""
        book_id = normalize_book_id(raw_input)
        self._require_credential()
        existing = self.repository.get_subscription(book_id)
        if existing:
            return existing
        article, meta = await self.client.fetch_cover(book_id)
        sub = MpSubscription(
            book_id=book_id,
            name=meta.get("name", "") or book_id,
            avatar=meta.get("avatar", ""),
        )
        self.repository.upsert_subscription(sub)
        # 顺手把最新一篇入库，订阅即有内容
        self.repository.upsert_articles(book_id, [article])
        return self.repository.refresh_subscription_stats(book_id, "ok") or sub

    def list_subscriptions(self) -> list[MpSubscription]:
        return self.repository.list_subscriptions()

    def delete_subscription(self, book_id: str) -> bool:
        return self.repository.delete_subscription(book_id)

    def list_articles(self, book_id: str, limit: int, cursor: str | None) -> tuple[list, str | None]:
        articles = self.repository.list_articles(book_id)
        start = 0
        if cursor:
            ids = [a.review_id for a in articles]
            start = ids.index(cursor) + 1 if cursor in ids else 0
        page = articles[start : start + limit]
        next_cursor = page[-1].review_id if page and start + limit < len(articles) else None
        return page, next_cursor

    # ---- 同步 ----

    async def sync_all(self) -> SyncSummary:
        self._require_credential()
        summary = SyncSummary(subscriptions=0)
        details = []
        for sub in self.repository.list_subscriptions():
            summary.subscriptions += 1
            result = await self.sync_subscription(sub.book_id)
            details.append(result)
            if result.status == "ok":
                summary.ok_count += 1
            else:
                summary.error_count += 1
            summary.new_articles += result.new_articles
        summary.details = details
        summary.finished_at = now_iso()
        return summary

    async def sync_subscription(self, book_id: str) -> SubscriptionSyncResult:
        sub = self.repository.get_subscription(book_id)
        name = sub.name if sub else book_id
        articles, note = [], ""
        try:
            articles = await self.client.fetch_articles(book_id)
        except WereadAPIError as exc:
            if exc.kind == "auth":
                # 列表接口在该账号已废弃（-2041）时回退 cover 增量
                try:
                    article, _ = await self.client.fetch_cover(book_id)
                    articles, note = [article], "（列表接口不可用，cover 增量）"
                except WereadAPIError as cover_exc:
                    status = "auth_error" if cover_exc.kind == "auth" else "error"
                    self.repository.refresh_subscription_stats(book_id, status, cover_exc.message)
                    return SubscriptionSyncResult(
                        book_id=book_id, name=name, status=status,
                        total_articles=self.repository.article_count(book_id),
                        message=cover_exc.message,
                    )
            elif exc.kind == "rate_limit":
                self.repository.refresh_subscription_stats(book_id, "error", exc.message)
                return SubscriptionSyncResult(
                    book_id=book_id, name=name, status="error",
                    total_articles=self.repository.article_count(book_id),
                    message=exc.message,
                )
            else:
                self.repository.refresh_subscription_stats(book_id, "error", exc.message)
                return SubscriptionSyncResult(
                    book_id=book_id, name=name, status="error",
                    total_articles=self.repository.article_count(book_id),
                    message=exc.message,
                )
        new_count = self.repository.upsert_articles(book_id, articles)
        self.repository.refresh_subscription_stats(book_id, "ok", note)
        return SubscriptionSyncResult(
            book_id=book_id,
            name=name,
            status="ok",
            new_articles=new_count,
            total_articles=self.repository.article_count(book_id),
            message=note,
        )
