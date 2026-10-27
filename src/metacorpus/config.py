from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MetaCorpus 元语助手 API"
    data_dir: Path = Path("./data")
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
    # 微信读书请求最小间隔（秒），防频率限制
    weread_request_interval_seconds: float = 2.0
    # 定时同步间隔（分钟），0 = 关闭内置调度
    weread_sync_interval_minutes: int = 120
    # 告警 Webhook（飞书/钉钉机器人地址，空 = 不告警）
    weread_webhook_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
