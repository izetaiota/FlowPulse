from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from douyin_transcribe.api.routes import get_pipeline, get_repository, router
from douyin_transcribe.config import get_settings
from douyin_transcribe.resolvers.api import ApiResolver
from douyin_transcribe.resolvers.router import ResolverRouter
from douyin_transcribe.resolvers.share_page import SharePageResolver
from douyin_transcribe.services.pipeline import PipelineService
from douyin_transcribe.storage.tasks import TaskRepository
from douyin_transcribe.transcribers.mock import MockTranscriber
from douyin_transcribe.transcribers.openai_api import OpenAITranscriber
from douyin_transcribe.transcribers.router import TranscriberRouter
from douyin_transcribe.transcribers.sensevoice import SenseVoiceTranscriber
from douyin_transcribe.transcribers.tingwu import TingwuTranscriber
from douyin_transcribe.transcribers.whisper import WhisperTranscriber
from xhs_spider.integration.routes import get_xhs_service, router as xhs_router
from xhs_spider.integration.service import XhsService


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
        yield
        await client.aclose()

    xhs_service = XhsService(settings.data_dir)

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.include_router(xhs_router)
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_xhs_service] = lambda: xhs_service
    app.state.pipeline = pipeline
    app.state.repository = repository
    app.state.xhs_service = xhs_service
    return app


app = create_app()
