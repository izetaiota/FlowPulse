"""微信读书采集模块的数据模型。"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_book_id(raw: str) -> str:
    """从任意输入（bookId、网页/App 复制的链接）提取 MP_WXS_ 公众号 bookId。

    支持的输入形态：
      - MP_WXS_3012726261
      - https://weread.qq.com/web/mp/reader/MP_WXS_3012726261
      - https://weread.qq.com/#web/reader/...（含 MP_WXS_ 片段）
    """
    import re

    text = (raw or "").strip()
    match = re.search(r"(MP_WXS_[A-Za-z0-9]+)", text)
    if not match:
        raise ValueError("无法从输入中识别公众号 bookId（形如 MP_WXS_xxxxxxxx）")
    return match.group(1)


class MpSubscription(BaseModel):
    """一个订阅的公众号（对应微信读书里的公众号"书籍"）。"""

    book_id: str
    name: str = ""
    avatar: str = ""
    added_at: str = Field(default_factory=now_iso)
    last_sync_at: str | None = None
    last_sync_status: str = "never"  # never | ok | error | auth_error
    last_error: str = ""
    article_count: int = 0


class MpArticle(BaseModel):
    """一篇公众号文章（reviewId 全局唯一）。"""

    review_id: str
    book_id: str
    title: str = ""
    link: str = ""
    cover: str = ""
    digest: str = ""
    publish_time: int = 0
    created_at: str = Field(default_factory=now_iso)


class MpArticleContent(BaseModel):
    """文章正文（按需抓取，存 HTML；图片已加 referrerpolicy 防盗链处理）。"""

    review_id: str
    book_id: str
    title: str = ""
    content_html: str
    publish_time: int = 0
    fetched_at: str = Field(default_factory=now_iso)


class CredentialState(BaseModel):
    """微信读书登录凭证（Cookie）。"""

    cookie: str
    saved_at: str = Field(default_factory=now_iso)
    last_validated_at: str | None = None
    valid: bool | None = None
    last_error: str = ""


class SubscriptionSyncResult(BaseModel):
    book_id: str
    name: str = ""
    status: str = "ok"  # ok | error | auth_error
    new_articles: int = 0
    total_articles: int = 0
    message: str = ""


class SyncSummary(BaseModel):
    started_at: str = Field(default_factory=now_iso)
    finished_at: str = Field(default_factory=now_iso)
    subscriptions: int = 0
    ok_count: int = 0
    error_count: int = 0
    new_articles: int = 0
    details: list[SubscriptionSyncResult] = Field(default_factory=list)


class CredentialUpdateRequest(BaseModel):
    cookie: str


class SubscriptionCreateRequest(BaseModel):
    """添加订阅：粘贴 bookId 或微信读书公众号链接。"""

    input: str
