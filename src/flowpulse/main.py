from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from flowpulse.config import get_settings
from flowpulse.core.auth import init_auth, require_auth
from flowpulse.core.auth import router as auth_router
from flowpulse.modules.accounts import get_account_service
from flowpulse.modules.accounts import router as accounts_router
from flowpulse.modules.douyin.api.routes import get_pipeline, get_repository, router
from flowpulse.modules.menu import get_menu_repository
from flowpulse.modules.menu import router as menu_router
from flowpulse.modules.notify import (
    get_notify_store,
    get_weread_notifier,
)
from flowpulse.modules.notify import router as notify_router
from flowpulse.modules.queue import get_queue_service
from flowpulse.modules.queue import router as queue_router
from flowpulse.modules.weread.api import (
    get_weread_cookie_refresher,
    get_weread_qr_login,
    get_weread_scheduler,
    get_weread_service,
)
from flowpulse.modules.weread.api import (
    router as weread_router,
)
from flowpulse.modules.xhs.integration.routes import (
    get_xhs_credential_checker,
    get_xhs_service,
)
from flowpulse.modules.xhs.integration.routes import router as xhs_router
from flowpulse.modules.xhs.monitoring import (
    get_monitor_scheduler,
    get_monitor_service,
)
from flowpulse.modules.xhs.monitoring import router as xhs_monitor_router
from flowpulse.runtime import build_runtime
from flowpulse.static_site import mount_static_site


def create_app() -> FastAPI:
    settings = get_settings()
    runtime = build_runtime(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime.weread_scheduler.start()
        runtime.weread_cookie_refresher.start()
        runtime.xhs_credential_checker.start()
        runtime.xhs_monitor_scheduler.start()
        yield
        await runtime.xhs_monitor_scheduler.stop()
        await runtime.weread_scheduler.stop()
        await runtime.weread_cookie_refresher.stop()
        await runtime.xhs_credential_checker.stop()
        await runtime.aclose()

    init_auth(
        settings.admin_username,
        settings.admin_password,
        settings.data_dir,
        runtime.auth_store,
    )

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    # 登录/会话接口免鉴权；业务路由在配置 ADMIN_PASSWORD 后统一要求 Bearer Token
    app.include_router(auth_router)
    app.include_router(router, dependencies=[Depends(require_auth)])
    app.include_router(xhs_router, dependencies=[Depends(require_auth)])
    app.include_router(xhs_monitor_router, dependencies=[Depends(require_auth)])
    app.include_router(weread_router, dependencies=[Depends(require_auth)])
    app.include_router(menu_router, dependencies=[Depends(require_auth)])
    app.include_router(notify_router, dependencies=[Depends(require_auth)])
    app.include_router(accounts_router, dependencies=[Depends(require_auth)])
    app.include_router(queue_router, dependencies=[Depends(require_auth)])
    app.dependency_overrides[get_pipeline] = lambda: runtime.pipeline
    app.dependency_overrides[get_repository] = lambda: runtime.task_repository
    app.dependency_overrides[get_xhs_service] = lambda: runtime.xhs_service
    app.dependency_overrides[get_xhs_credential_checker] = lambda: runtime.xhs_credential_checker
    app.dependency_overrides[get_weread_service] = lambda: runtime.weread_service
    app.dependency_overrides[get_weread_scheduler] = lambda: runtime.weread_scheduler
    app.dependency_overrides[get_weread_qr_login] = lambda: runtime.weread_qr_login
    app.dependency_overrides[get_weread_cookie_refresher] = lambda: runtime.weread_cookie_refresher
    app.dependency_overrides[get_menu_repository] = lambda: runtime.menu_repository
    app.dependency_overrides[get_notify_store] = lambda: runtime.notify_store
    app.dependency_overrides[get_weread_notifier] = lambda: runtime.weread_notifier
    app.dependency_overrides[get_account_service] = lambda: runtime.account_service
    app.dependency_overrides[get_queue_service] = lambda: runtime.queue_service
    app.dependency_overrides[get_monitor_service] = lambda: runtime.xhs_monitor_service
    app.dependency_overrides[get_monitor_scheduler] = lambda: runtime.xhs_monitor_scheduler
    app.state.pipeline = runtime.pipeline
    app.state.repository = runtime.task_repository
    app.state.xhs_service = runtime.xhs_service
    app.state.weread_service = runtime.weread_service
    app.state.weread_scheduler = runtime.weread_scheduler
    app.state.weread_qr_login = runtime.weread_qr_login
    app.state.weread_cookie_refresher = runtime.weread_cookie_refresher
    if settings.static_dir:
        mount_static_site(app, settings.static_dir)
    return app


app = create_app()
