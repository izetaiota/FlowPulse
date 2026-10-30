"""服务装配工厂：main.py（Web 应用）与 console（CLI 任务）共用的接线层。

把「从 Settings 构造全部服务栈」收敛到一处，Web 启动与一次性任务使用同一份
构造逻辑，避免两处接线随配置项增加而漂移。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from flowpulse.config import Settings
from flowpulse.core.auth import AuthUserStore
from flowpulse.core.crypto import CredentialCipher
from flowpulse.core.notify import WebhookNotifier
from flowpulse.modules.accounts import AccountRepository, AccountService, WereadProvider, XhsProvider
from flowpulse.modules.douyin.resolvers.api import ApiResolver
from flowpulse.modules.douyin.resolvers.router import ResolverRouter
from flowpulse.modules.douyin.resolvers.share_page import SharePageResolver
from flowpulse.modules.douyin.services.pipeline import PipelineService
from flowpulse.modules.douyin.storage.tasks import TaskRepository
from flowpulse.modules.douyin.transcribers.mock import MockTranscriber
from flowpulse.modules.douyin.transcribers.openai_api import OpenAITranscriber
from flowpulse.modules.douyin.transcribers.router import TranscriberRouter
from flowpulse.modules.douyin.transcribers.sensevoice import SenseVoiceTranscriber
from flowpulse.modules.douyin.transcribers.tingwu import TingwuTranscriber
from flowpulse.modules.douyin.transcribers.whisper import WhisperTranscriber
from flowpulse.modules.menu import MenuRepository
from flowpulse.modules.notify import NotifyStore
from flowpulse.modules.queue import QueueService
from flowpulse.modules.weread.qrlogin import WereadQrLoginManager
from flowpulse.modules.weread.refresh import WereadCookieRefresher
from flowpulse.modules.weread.scheduler import WereadScheduler
from flowpulse.modules.weread.service import WereadService
from flowpulse.modules.weread.storage import WereadRepository
from flowpulse.modules.xhs.integration.credential_check import XhsCredentialChecker
from flowpulse.modules.xhs.integration.service import XhsService


@dataclass
class Runtime:
    """一次装配好的全部服务栈。常驻调度循环是否启动由使用方决定（Web 启动、CLI 不启动）。"""

    settings: Settings
    client: httpx.AsyncClient
    task_repository: TaskRepository
    pipeline: PipelineService
    xhs_service: XhsService
    xhs_credential_checker: XhsCredentialChecker
    # PG 模式下实际类型为 PgWereadRepository（接口与文件仓储一致）
    weread_repository: WereadRepository
    weread_notifier: WebhookNotifier | None
    weread_service: WereadService
    weread_scheduler: WereadScheduler
    weread_qr_login: WereadQrLoginManager
    weread_cookie_refresher: WereadCookieRefresher
    menu_repository: MenuRepository
    auth_store: AuthUserStore
    notify_store: NotifyStore
    account_service: AccountService
    queue_service: QueueService
    db_engine: object | None = None

    async def aclose(self) -> None:
        """释放与调度循环无关的资源（HTTP 客户端、浏览器驱动、数据库连接池）。"""
        await self.client.aclose()
        await self.weread_qr_login.aclose()
        if self.db_engine is not None:
            self.db_engine.dispose()


def build_runtime(settings: Settings) -> Runtime:
    repository = TaskRepository(settings.data_dir)
    client = httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        headers={"Accept-Language": "zh-CN,zh;q=0.9"},
    )
    resolver = ResolverRouter(
        [SharePageResolver(client), ApiResolver(client, settings.douyin_resolver_base_url)]
    )
    available_engines = {
        "mock": MockTranscriber(),
        "whisper": WhisperTranscriber(
            settings.whisper_model,
            settings.whisper_device,
            settings.whisper_compute_type,
            settings.whisper_language,
        ),
        "sensevoice": SenseVoiceTranscriber(),
        "tingwu": TingwuTranscriber(
            settings.aliyun_access_key_id,
            settings.aliyun_access_key_secret,
            settings.tingwu_app_key,
            settings.aliyun_oss_bucket,
            settings.aliyun_oss_endpoint,
            settings.aliyun_oss_prefix,
            settings.tingwu_region,
            settings.tingwu_language_hint,
            settings.tingwu_poll_interval_seconds,
            settings.tingwu_timeout_seconds,
        ),
        "openai": OpenAITranscriber(
            client,
            settings.openai_transcribe_base_url,
            settings.openai_transcribe_api_key,
            settings.openai_transcribe_model,
        ),
    }
    ordered_names = [
        settings.transcribe_engine,
        "whisper",
        "sensevoice",
        "tingwu",
        "openai",
        "mock",
    ]
    engines = []
    for name in ordered_names:
        if name in available_engines and available_engines[name] not in engines:
            engines.append(available_engines[name])
    transcriber = TranscriberRouter(engines)
    pipeline = PipelineService(
        repository,
        resolver,
        transcriber,
        client,
        settings.max_download_bytes,
    )

    xhs_service = XhsService(
        settings.data_dir,
        proxy=settings.xhs_proxy or None,
        credential_key=settings.xhs_credential_key,
    )

    # 存储双模式：DATABASE_URL 指向 PostgreSQL 时用数据库仓储，否则文件存储（零依赖默认）
    db_engine = None
    db_sessionmaker = None
    if settings.database_url:
        from flowpulse.db.engine import create_engine_and_sessionmaker, ensure_tables
        from flowpulse.modules.weread.pg_repository import PgWereadRepository

        db_engine, db_sessionmaker = create_engine_and_sessionmaker(settings.database_url)
        ensure_tables(db_engine)  # 幂等建表；结构演进走 Alembic
        weread_repository = PgWereadRepository(
            db_sessionmaker,
            credential_key=settings.weread_credential_key,
            key_file=settings.data_dir / "weread" / ".credential_key",
        )
    else:
        weread_repository = WereadRepository(
            settings.data_dir, credential_key=settings.weread_credential_key
        )
    if settings.weread_cookie and not weread_repository.get_credential():
        weread_repository.save_credential(settings.weread_cookie)
    # 通知渠道库（页面可管理，运行时与环境变量渠道合并生效）
    notify_store = NotifyStore(
        db_sessionmaker,  # DATABASE_URL 模式走 fp_notify_channels/fp_notify_logs 表
        settings.data_dir / "notify",
    )
    # 始终构造 notifier：渠道动态判断（env 为空时页面添加的渠道同样生效）
    weread_notifier = WebhookNotifier(
        client, [settings.weread_webhook_url, settings.weread_notify_channels],
        store=notify_store,
    )
    menu_repository = MenuRepository(
        db_sessionmaker,  # DATABASE_URL 模式走 fp_app_menus 表，否则 data/app/menus.json
        settings.data_dir / "app" / "menus.json",
    )
    auth_store = AuthUserStore(
        db_sessionmaker,  # DATABASE_URL 模式走 fp_users 表，否则 data/auth/users.json
        settings.data_dir / "auth" / "users.json",
    )

    xhs_credential_checker = XhsCredentialChecker(
        xhs_service,
        settings.data_dir,
        notifier=weread_notifier,  # Webhook 告警与 weread 共用同一地址
        interval_minutes=settings.xhs_credential_check_minutes,
    )
    weread_service = WereadService(
        weread_repository,
        client,
        request_interval_seconds=settings.weread_request_interval_seconds,
        rss_full_text=settings.weread_rss_full_text,
        notifier=weread_notifier,  # 新文章推送与告警共用通知渠道
    )
    weread_qr_login = WereadQrLoginManager(
        settings.data_dir / "weread" / "browser_profile",
        on_cookie=weread_service.save_credential,
    )
    weread_scheduler = WereadScheduler(
        weread_service,
        weread_repository,
        notifier=weread_notifier,
        interval_minutes=settings.weread_sync_interval_minutes,
        qr_login=weread_qr_login,  # Cookie 失效告警可附带扫码二维码
    )
    weread_cookie_refresher = WereadCookieRefresher(
        weread_qr_login,
        weread_service,
        weread_repository,
        notifier=weread_notifier,
        interval_hours=settings.weread_cookie_refresh_hours,
    )
    # 同步遇 Cookie 失效时自动无头续期（自愈）；仅在启用续期调度时挂接
    # （WEREAD_COOKIE_REFRESH_HOURS=0 的场景——如无桌面的容器——不会意外拉起浏览器）
    if settings.weread_cookie_refresh_hours > 0:
        weread_service.attach_self_heal(weread_cookie_refresher.run_once)

    # 统一账号中心（P0）：builtin 提供方聚合 weread/xhs，managed 账号凭证独立加密
    account_repository = AccountRepository(
        db_sessionmaker,  # DATABASE_URL 模式走 fp_accounts 表，否则 data/accounts/accounts.json
        settings.data_dir / "accounts" / "accounts.json",
    )
    account_service = AccountService(
        account_repository,
        providers=[
            WereadProvider(weread_repository, weread_service, weread_qr_login),
            XhsProvider(xhs_service, xhs_credential_checker),
        ],
        cipher=CredentialCipher(
            key_file=settings.data_dir / "accounts" / ".credential_key"
        ),
    )
    # 统一任务队列视图（P0）：聚合抖音转写与小红书抓取任务
    queue_service = QueueService(repository, pipeline, xhs_service.jobs)

    return Runtime(
        settings=settings,
        client=client,
        task_repository=repository,
        pipeline=pipeline,
        xhs_service=xhs_service,
        xhs_credential_checker=xhs_credential_checker,
        weread_repository=weread_repository,
        weread_notifier=weread_notifier,
        weread_service=weread_service,
        weread_scheduler=weread_scheduler,
        weread_qr_login=weread_qr_login,
        weread_cookie_refresher=weread_cookie_refresher,
        menu_repository=menu_repository,
        auth_store=auth_store,
        notify_store=notify_store,
        account_service=account_service,
        queue_service=queue_service,
        db_engine=db_engine,
    )
