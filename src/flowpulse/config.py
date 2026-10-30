from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "心流 FlowPulse API"
    data_dir: Path = Path("./data")
    # 前端静态资源目录（Docker 单容器部署时由 FastAPI 伺服，空 = 不挂载）
    static_dir: str = ""
    # 数据库连接（PostgreSQL）：postgresql+psycopg://user:pass@host:5432/flowpulse
    # 空 = 文件存储（零依赖默认）；设置后 weread 等模块切换到数据库存储
    database_url: str = ""
    # Web 登录（单账号，无菜单权限）：ADMIN_PASSWORD 为空 = 鉴权关闭（本地直通）
    admin_username: str = "admin"
    admin_password: str = ""
    transcribe_engine: str = "mock"
    max_download_bytes: int = 500 * 1024 * 1024
    request_timeout_seconds: float = 30
    douyin_resolver_base_url: str = ""
    openai_transcribe_base_url: str = ""
    openai_transcribe_api_key: str = ""
    openai_transcribe_model: str = "whisper-1"
    whisper_model: str = "small"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_language: str | None = "zh"
    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""
    aliyun_oss_bucket: str = ""
    aliyun_oss_endpoint: str = ""
    aliyun_oss_prefix: str = "douyin-transcribe"
    tingwu_app_key: str = ""
    tingwu_region: str = "cn-beijing"
    tingwu_language_hint: str = "cn"
    tingwu_poll_interval_seconds: float = 5
    tingwu_timeout_seconds: float = 1800

    # --- Xiaohongshu (XHS) ---
    # Optional outbound proxy for XHS requests, e.g. "http://127.0.0.1:7890".
    # Leave empty to connect directly.
    xhs_proxy: str = ""

    # --- WeRead（微信公众号 RSS 采集通道）---
    # 微信读书 Cookie（wr_vid=...; wr_skey=... 整串）；也可用 API 端点动态保存
    weread_cookie: str = ""
    # Cookie 静态加密密钥（Fernet，base64 urlsafe 32 字节）；空 = 自动生成并保存到 data/weread/.credential_key
    weread_credential_key: str = ""
    # 微信读书请求最小间隔（秒），防频率限制
    weread_request_interval_seconds: float = 2.0
    # 定时同步间隔（分钟），0 = 关闭内置调度。公众号低频更新 + 微信读书风控，
    # 推荐 30~60：30 推送更及时，60 更稳；不建议低于 15
    weread_sync_interval_minutes: int = 60
    # 告警 Webhook（飞书/钉钉机器人地址，空 = 不告警）
    weread_webhook_url: str = ""
    # 附加通知渠道（逗号分隔多个 webhook 地址，与 weread_webhook_url 合并去重）
    weread_notify_channels: str = ""
    # RSS 是否输出全文（content:encoded，仅对已抓取过正文的文章生效）
    weread_rss_full_text: bool = False
    # Cookie 自动续期间隔（小时）：无头复用扫码浏览器 profile 静默刷新，0 = 关闭
    weread_cookie_refresh_hours: int = 24
    # --- XHS（小红书）---
    # 小红书登录态定时校验（分钟），掉线时推 Webhook 告警，0 = 关闭
    xhs_credential_check_minutes: int = 360
    # 小红书 Cookie 静态加密密钥（Fernet）；空 = 自动生成 data/xhs/.credential_key
    xhs_credential_key: str = ""
    # --- XHS 作品监控（P1）---
    # 监控调度总开关（false = 不启动后台扫描，API 仍可用手动触发）
    xhs_monitor_enabled: bool = True
    # 调度轮询间隔（秒）
    xhs_monitor_tick_seconds: int = 60
    # 新建监控目标的默认扫描周期（分钟），目标级可覆盖
    xhs_monitor_default_interval_minutes: int = 30

    # --- 抖音平台（P3）---
    # 抖音作品监控调度总开关
    douyin_monitor_enabled: bool = True
    # 抖音监控调度轮询间隔（秒）
    douyin_monitor_tick_seconds: int = 60
    # 拦截式读取是否无头（扫码登录始终有头；无头失败时可改 false 观察页面）
    douyin_browser_headless: bool = True
    # 抖音发布队列 worker 总开关（发布执行始终有头，风控验证需人工）
    douyin_publish_enabled: bool = True

    # --- 快手平台（P5-T5.1）---
    ks_monitor_enabled: bool = True
    ks_monitor_tick_seconds: int = 60
    ks_browser_headless: bool = True

    # --- 写操作风控闸（P4）---
    risk_enabled: bool = True
    # 单账号小时/日写操作配额（0 = 不限）
    risk_hourly_limit: int = 10
    risk_daily_limit: int = 50
    # 安静时段（本地时钟，如 23:00-07:00 跨午夜；空 = 关闭）
    risk_quiet_hours: str = "23:00-07:00"

    # --- 浏览器会话层（P0.5 骨架，P3 抖音接入时启用）---
    # 浏览器登录总开关（当前仅作预留；patchright 为可选依赖 browser 组）
    browser_enabled: bool = False
    # 常驻浏览器上下文上限（超量按最久未用回收）
    browser_max_live_contexts: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
