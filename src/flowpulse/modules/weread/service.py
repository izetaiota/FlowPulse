"""微信读书采集服务：凭证管理、订阅解析、增量同步。"""

from __future__ import annotations

import re
import time

import httpx

from flowpulse.core.notify import WebhookNotifier
from flowpulse.modules.weread.client import WereadAPIError, WereadClient
from flowpulse.modules.weread.models import (
    MpArticleContent,
    MpSubscription,
    SubscriptionSyncResult,
    SubscriptionUpdateRequest,
    SyncSummary,
    normalize_book_id,
    now_iso,
)
from flowpulse.modules.weread.storage import WereadRepository

# Cookie 失效自愈（触发无头续期）的冷却时间，防止多订阅连环拉起浏览器
SELF_HEAL_COOLDOWN_SECONDS = 900.0


class NeedWereadLinkError(Exception):
    """已识别公众号名称，但需要用户补充该公众号在微信读书里的链接/bookId。"""

    def __init__(self, name: str, message: str):
        super().__init__(message)
        self.name = name
        self.message = message


def _digest_from_html(html: str, limit: int = 120) -> str:
    """从正文 HTML 提取纯文本摘要（cover 通道不带 digest，读到正文后补）。"""
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


class WereadService:
    def __init__(
        self,
        repository: WereadRepository,
        http_client: httpx.AsyncClient,
        request_interval_seconds: float = 2.0,
        rss_full_text: bool = False,
        notifier: WebhookNotifier | None = None,
    ):
        self.repository = repository
        self.rss_full_text = rss_full_text
        self._notifier = notifier
        self.client = WereadClient(
            http_client,
            lambda: (credential.cookie if (credential := self.repository.get_credential()) else ""),
            request_interval_seconds,
        )
        self._self_heal = None
        self._self_heal_until = 0.0

    def attach_self_heal(self, heal) -> None:
        """注入自愈回调（main 装配时指向 Cookie 无头续期），同步遇登录失效时自动触发。"""
        self._self_heal = heal

    async def _try_self_heal(self) -> bool:
        heal = self._self_heal
        if not heal:
            return False
        if time.monotonic() < self._self_heal_until:
            return False
        self._self_heal_until = time.monotonic() + SELF_HEAL_COOLDOWN_SECONDS
        try:
            result = await heal()
        except Exception:  # noqa: BLE001 - 自愈失败不影响同步主流程
            return False
        return bool(result.get("ok"))

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
        """添加订阅：支持微信读书链接/bookId、公众号文章链接、公众号名称。

        文章链接会先提取公众号名称，再尝试微信读书搜索自动定位 bookId；
        搜索接口不可用（实测对该账号恒 -2012）或未命中时抛 NeedWereadLinkError，
        由前端弹出向导引导用户补充微信读书链接。
        """
        text = (raw_input or "").strip()
        try:
            book_id = normalize_book_id(text)
        except ValueError:
            book_id = await self._resolve_book_id_from_text(text)
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

    async def _resolve_book_id_from_text(self, text: str) -> str:
        """文章链接 → 公众号名称；或直接把输入当名称 → 微信读书搜索定位 bookId。"""
        name = text
        if "http" in text or "www." in text:
            if "mp.weixin.qq.com" not in text:
                raise ValueError("链接暂不支持：请粘贴微信读书公众号链接或 mp.weixin.qq.com 文章链接")
            account = await self.client.fetch_article_account(text)
            name = account.get("name", "")
        if not name:
            raise ValueError("请粘贴微信读书公众号链接、公众号文章链接或公众号名称")
        try:
            hits = await self.client.search_accounts(name)
        except WereadAPIError as exc:
            raise NeedWereadLinkError(
                name, f"公众号只能在手机微信读书 App 中搜索：请在 App 里找到「{name}」，复制其链接后粘贴完成订阅"
            ) from exc
        for hit in hits:
            if hit.get("title") == name:
                return hit["book_id"]
        if len(hits) == 1:
            return hits[0]["book_id"]
        raise NeedWereadLinkError(
            name, f"未能自动定位「{name}」，请在手机微信读书 App 中打开该公众号并复制链接完成订阅"
        )

    def list_subscriptions(self) -> list[MpSubscription]:
        return self.repository.list_subscriptions()

    def update_subscription(
        self, book_id: str, request: SubscriptionUpdateRequest
    ) -> MpSubscription | None:
        """编辑订阅的可定制项（RSS 输出 / 清洗规则 / 推送开关），保留同步状态字段。"""
        sub = self.repository.get_subscription(book_id)
        if not sub:
            return None
        sub.name = request.name.strip() or sub.name
        sub.rss_title = request.rss_title.strip()
        sub.rss_description = request.rss_description.strip()
        sub.rss_full_text = request.rss_full_text
        sub.rss_max_items = request.rss_max_items
        sub.strip_keywords = request.strip_keywords.strip()
        sub.notify_new = request.notify_new
        sub.sync_interval_minutes = request.sync_interval_minutes
        return self.repository.upsert_subscription(sub)

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

    async def get_article_content(self, book_id: str, review_id: str) -> MpArticleContent:
        """站内阅读：正文按需抓取，抓过即缓存（不重复请求）。

        抓取顺序：公开原文页（无需 Cookie，富文本完整）→ 微信读书代理页兜底。
        公开页顺带提取发布时间，回填文章记录（cover 通道的文章没有时间）。
        """
        article = next(
            (a for a in self.repository.list_articles(book_id) if a.review_id == review_id),
            None,
        )
        if not article:
            raise WereadAPIError("api", "not_found", "文章不存在")
        cached = self.repository.get_content(review_id)
        if cached and cached.publish_time > 0:
            self._backfill_publish_time(article, cached.publish_time)
            self._backfill_digest(article, cached.content_html)
            return cached

        content_html = cached.content_html if cached else ""
        publish_time = cached.publish_time if cached else 0
        errors: list[str] = []
        if article.link:
            try:
                content_html, publish_time = await self.client.fetch_public_article(article.link)
            except WereadAPIError as exc:
                errors.append(f"原文页：{exc.message}")
        if not content_html:
            try:
                self._require_credential()
                content_html = await self.client.fetch_content_html(review_id)
            except WereadAPIError as exc:
                errors.append(f"微信读书：{exc.message}")
        if not content_html:
            raise WereadAPIError("api", "content_failed", "；".join(errors) or "正文获取失败")
        self._backfill_publish_time(article, publish_time)
        self._backfill_digest(article, content_html)
        return self.repository.save_content(
            MpArticleContent(
                review_id=review_id,
                book_id=book_id,
                title=article.title,
                content_html=content_html,
                publish_time=publish_time,
            )
        )

    def _backfill_publish_time(self, article, publish_time: int) -> None:
        """把读到的发布时间写回文章记录，列表/RSS 排序与展示用。"""
        if publish_time > 0 and article.publish_time == 0:
            article.publish_time = publish_time
            self.repository.set_article_publish_time(article.book_id, article.review_id, publish_time)

    def _backfill_digest(self, article, content_html: str) -> None:
        """把正文首段摘要写回文章记录（RSS description 用）。"""
        if article.digest:
            return
        digest = _digest_from_html(content_html)
        if digest:
            article.digest = digest
            self.repository.set_article_digest(article.book_id, article.review_id, digest)

    def load_contents(self, articles: list) -> dict[str, str]:
        """RSS 全文模式用：批量取已缓存的正文。"""
        contents: dict[str, str] = {}
        for article in articles:
            cached = self.repository.get_content(article.review_id)
            if cached:
                contents[article.review_id] = cached.content_html
        return contents

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
            if exc.kind != "auth":
                self.repository.refresh_subscription_stats(book_id, "error", exc.message)
                return SubscriptionSyncResult(
                    book_id=book_id,
                    name=name,
                    status="error",
                    total_articles=self.repository.article_count(book_id),
                    message=exc.message,
                )
            # 列表接口对该账号可能已废弃（恒 -2041）：回退 cover 增量
            try:
                article, _ = await self.client.fetch_cover(book_id)
                articles, note = [article], "（列表接口不可用，cover 增量）"
            except WereadAPIError as cover_exc:
                if cover_exc.kind == "auth" and await self._try_self_heal():
                    # Cookie 被其他端轮换失效 → 自动无头续期成功 → 重试一次
                    try:
                        article, _ = await self.client.fetch_cover(book_id)
                        articles, note = [article], "（Cookie 已自动续期，cover 增量）"
                    except WereadAPIError:
                        pass
                if not articles:
                    status = "auth_error" if cover_exc.kind == "auth" else "error"
                    self.repository.refresh_subscription_stats(book_id, status, cover_exc.message)
                    return SubscriptionSyncResult(
                        book_id=book_id,
                        name=name,
                        status=status,
                        total_articles=self.repository.article_count(book_id),
                        message=cover_exc.message,
                    )
        fresh = self.repository.upsert_articles(book_id, articles)
        self.repository.refresh_subscription_stats(book_id, "ok", note)
        if fresh and sub and sub.notify_new:
            await self._push_new_articles(sub, fresh)
        return SubscriptionSyncResult(
            book_id=book_id,
            name=name,
            status="ok",
            new_articles=len(fresh),
            total_articles=self.repository.article_count(book_id),
            message=note,
        )

    async def _push_new_articles(
        self, sub: MpSubscription, articles: list
    ) -> None:
        """新文章到达推送：标题 + 原文链接发到全部通知渠道（每次同步最多列 10 篇）。"""
        notifier = self._notifier
        if not notifier or not notifier.configured:
            return
        lines = [f"[{a.title or '（无标题）'}]({a.link})" for a in articles[:10]]
        if len(articles) > 10:
            lines.append(f"…等共 {len(articles)} 篇")
        await notifier.send(
            f"weread:new:{sub.book_id}",
            f"公众号「{sub.name or sub.book_id}」更新 {len(articles)} 篇新文章",
            "\n".join(lines),
            cooldown_seconds=0,  # 有新文章必发（同步本身有间隔控制）
        )
