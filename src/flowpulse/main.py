from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from flowpulse.config import get_settings
from flowpulse.core.notify import WebhookNotifier
from flowpulse.modules.douyin.api.routes import get_pipeline, get_repository, router
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
from flowpulse.modules.weread.api import (
    get_weread_cookie_refresher,
    get_weread_qr_login,
    get_weread_scheduler,
    get_weread_service,
)
from flowpulse.modules.weread.api import (
    router as weread_router,
)
from flowpulse.modules.weread.qrlogin import WereadQrLoginManager
from flowpulse.modules.weread.refresh import WereadCookieRefresher
from flowpulse.modules.weread.scheduler import WereadScheduler
from flowpulse.modules.weread.service import WereadService
from flowpulse.modules.weread.storage import WereadRepository
from flowpulse.modules.xhs.integration.routes import get_xhs_service
from flowpulse.modules.xhs.integration.routes import router as xhs_router
from flowpulse.modules.xhs.integration.service import XhsService
from flowpulse.static_site import mount_static_site


def create_app() -> FastAPI:
    settings = get_settings()
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

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        weread_scheduler.start()
        weread_cookie_refresher.start()
        yield
        await client.aclose()
        await weread_scheduler.stop()
        await weread_cookie_refresher.stop()
        await weread_qr_login.aclose()
        if db_engine is not None:
            db_engine.dispose()

    xhs_service = XhsService(settings.data_dir, proxy=settings.xhs_proxy or None)

    # 存储双模式：DATABASE_URL 指向 PostgreSQL 时用数据库仓储，否则文件存储（零依赖默认）
    db_engine = None
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
    weread_notifier = (
        WebhookNotifier(client, settings.weread_webhook_url)
        if settings.weread_webhook_url
        else None
    )
    weread_service = WereadService(
        weread_repository,
        client,
        request_interval_seconds=settings.weread_request_interval_seconds,
        rss_full_text=settings.weread_rss_full_text,
    )
    weread_scheduler = WereadScheduler(
        weread_service,
        weread_repository,
        notifier=weread_notifier,
        interval_minutes=settings.weread_sync_interval_minutes,
    )
    weread_qr_login = WereadQrLoginManager(
        settings.data_dir / "weread" / "browser_profile",
        on_cookie=weread_service.save_credential,
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

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.include_router(xhs_router)
    app.include_router(weread_router)
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_xhs_service] = lambda: xhs_service
    app.dependency_overrides[get_weread_service] = lambda: weread_service
    app.dependency_overrides[get_weread_scheduler] = lambda: weread_scheduler
    app.dependency_overrides[get_weread_qr_login] = lambda: weread_qr_login
    app.dependency_overrides[get_weread_cookie_refresher] = lambda: weread_cookie_refresher
    app.state.pipeline = pipeline
    app.state.repository = repository
    app.state.xhs_service = xhs_service
    app.state.weread_service = weread_service
    app.state.weread_scheduler = weread_scheduler
    app.state.weread_qr_login = weread_qr_login
    app.state.weread_cookie_refresher = weread_cookie_refresher
    if settings.static_dir:
        mount_static_site(app, settings.static_dir)
    return app


app = create_app()
