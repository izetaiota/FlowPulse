"""微信读书采集模块的数据模型。"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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
        # App 分享链接（book-detail?...&v=...）里 bookId 以 hex 编码藏在 v 参数中，
        # 形如 4d505f5758535f(=MP_WXS_) 后跟数字的 hex（0x30-0x39 → "3x"）
        hex_match = re.search(r"4d505f5758535f((?:3[0-9]){4,15})", text)
        if hex_match:
            return "MP_WXS_" + bytes.fromhex(hex_match.group(1)).decode()
    if not match:
        raise ValueError(
            "无法识别公众号 bookId：需要粘贴微信读书里该公众号的链接或 bookId（MP_WXS_数字）。"
            "注意：公众号文章链接（mp.weixin.qq.com/s/...）不能用于订阅，"
            "请在微信读书 App 或网页版打开该公众号后复制其页面链接"
        )
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
    # --- RSS 输出定制（空值 = 跟随全局默认）---
    rss_title: str = ""
    rss_description: str = ""
    # None = 跟随全局 WEREAD_RSS_FULL_TEXT
    rss_full_text: bool | None = None
    # 0 = 默认条数（100）
    rss_max_items: int = 0
    # --- 正文清洗：逗号分隔 class/id 关键词，叠加内置默认规则 ---
    strip_keywords: str = ""
    # --- 新文章推送开关（需配置通知渠道）---
    notify_new: bool = True


class SubscriptionUpdateRequest(BaseModel):
    """编辑订阅：全量可编辑字段，rss_full_text 传 null 表示恢复跟随全局。"""

    name: str = ""
    rss_title: str = ""
    rss_description: str = ""
    rss_full_text: bool | None = None
    rss_max_items: int = Field(default=0, ge=0, le=500)
    strip_keywords: str = ""
    notify_new: bool = True


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


def article_sort_key(article: MpArticle) -> float:
    """排序用有效时间：优先发布时间；未回填（cover 通道初始为 0）的用入库时间兜底，
    避免最新文章在时间回填前沉底。"""
    if article.publish_time > 0:
        return float(article.publish_time)
    try:
        return datetime.fromisoformat(article.created_at).timestamp()
    except ValueError:
        return 0.0


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
