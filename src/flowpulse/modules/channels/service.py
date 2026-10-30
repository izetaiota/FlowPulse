"""视频号模块（T5.2）：账号扫码接入 + 本账号作品/资料快照（JSON 文件存储）。

视频号仅支持本账号数据（创作者助手拦截），无对外监控语义，故作品快照存
data/channels/*.json（文件存储；双模式部署同样适用——快照可随时重建）。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.modules.accounts.service import AccountService
from flowpulse.modules.browser import (
    LoginDriverState,
    LoginSessionState,
    ProfileAllocator,
)
from flowpulse.modules.browser import engine as browser_engine
from flowpulse.modules.channels.browser import (
    ChannelsBrowserFetcher,
    PLATFORM_URL,
    channels_storage_from_cookies,
)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])

ACCOUNT_KEY = "default"
QR_TIMEOUT_SECONDS = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_channels_service():
    raise RuntimeError("Dependency override is not configured")


class ChannelsStore:
    """本账号快照：data/channels/profile.json + works.json。"""

    def __init__(self, data_dir: Path):
        self.root = data_dir / "channels"
        self.root.mkdir(parents=True, exist_ok=True)

    def save_profile(self, profile: dict) -> None:
        atomic_write_json(self.root / "profile.json", {"profile": profile, "saved_at": _now_iso()})

    def get_profile(self) -> dict | None:
        data = read_json(self.root / "profile.json", {})
        return data.get("profile") or None

    def save_works(self, works: list[dict]) -> None:
        atomic_write_json(
            self.root / "works.json", {"works": works, "saved_at": _now_iso()}
        )

    def list_works(self) -> list[dict]:
        return read_json(self.root / "works.json", {}).get("works", [])


class ChannelsService:
    def __init__(self, account_service: AccountService, profiles_root: Path, store: ChannelsStore):
        self.account_service = account_service
        self.allocator = ProfileAllocator(profiles_root)
        self.store = store
        self.sessions: dict[str, dict[str, Any]] = {}

    def _login_state(self) -> tuple[str | None, dict | None]:
        account = self.account_service.repository.find_by_key("channels", ACCOUNT_KEY)
        if account is None:
            return None, None
        return None, account.get("storage_state") or None

    def _fetcher(self, headless: bool = True) -> ChannelsBrowserFetcher:
        return ChannelsBrowserFetcher(self._login_state, self.allocator.root, headless=headless)

    # ---- 状态 ----

    def status(self) -> dict:
        account = self.account_service.repository.find_by_key("channels", ACCOUNT_KEY)
        profile = self.store.get_profile()
        return {
            "configured": account is not None,
            "storage_state_available": bool(account and account.get("storage_state")),
            "nickname": (profile or {}).get("nickname", ""),
            "works_count": len(self.store.list_works()),
            "engine": browser_engine.browser_engine_name(),
        }

    # ---- 扫码登录 ----

    async def qr_start(self) -> dict:
        if browser_engine.browser_engine_name() == "none":
            raise RuntimeError("未安装浏览器引擎：pip install -e \".[browser]\" 或 pip install playwright")
        session_id = uuid.uuid4().hex
        state = LoginSessionState(platform="channels", account_key=ACCOUNT_KEY)
        state.transition(LoginDriverState.WAITING, "已打开视频号助手，请在浏览器中扫码登录")
        self.sessions[session_id] = {"state": state, "started_at": time.monotonic()}
        task = asyncio.create_task(self._qr_worker(session_id))
        self.sessions[session_id]["task"] = task
        return {"session_id": session_id, "state": state.state.value, "message": state.message}

    def qr_poll(self, session_id: str) -> dict:
        entry = self.sessions.get(session_id)
        if entry is None:
            return {"session_id": session_id, "state": "unknown", "message": "会话不存在或已结束"}
        state: LoginSessionState = entry["state"]
        if state.state == LoginDriverState.WAITING and time.monotonic() - entry["started_at"] > QR_TIMEOUT_SECONDS:
            state.transition(LoginDriverState.EXPIRED, "扫码超时，请重新发起")
        result = {"session_id": session_id, "state": state.state.value, "message": state.message}
        if state.state in (LoginDriverState.LOGGED_IN, LoginDriverState.FAILED, LoginDriverState.CANCELLED, LoginDriverState.EXPIRED):
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
            self.sessions.pop(session_id, None)
        return result

    def qr_cancel(self, session_id: str) -> dict:
        entry = self.sessions.pop(session_id, None)
        if entry:
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
            return {"cancelled": True}
        return {"cancelled": False}

    async def _qr_worker(self, session_id: str) -> None:
        entry = self.sessions.get(session_id)
        if entry is None:
            return
        state: LoginSessionState = entry["state"]
        profile = self.allocator.allocate("channels", "qr-login")
        context = None
        try:
            context = await browser_engine.launch_persistent_context(profile, headless=False)
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(PLATFORM_URL, wait_until="domcontentloaded", timeout=40000)
            deadline = time.monotonic() + QR_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                await asyncio.sleep(2)
                if "/login" not in (page.url or ""):
                    # 离开登录页即视为已登录：保存登录态
                    cookies = await context.cookies(["https://channels.weixin.qq.com"])
                    storage = channels_storage_from_cookies(cookies)
                    if storage:
                        self._persist_login(storage)
                        state.transition(LoginDriverState.LOGGED_IN, "登录成功，账号已保存")
                        return
                if self.sessions.get(session_id) is None:
                    return
            state.transition(LoginDriverState.EXPIRED, "扫码超时，请重新发起")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            try:
                state.transition(LoginDriverState.FAILED, f"登录失败：{exc}"[:200])
            except ValueError:
                pass
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:  # noqa: BLE001
                    pass

    def _persist_login(self, storage_state: dict) -> None:
        existing = self.account_service.repository.find_by_key("channels", ACCOUNT_KEY)
        if existing is None:
            account_id = self.account_service.repository.create_managed(
                "channels", ACCOUNT_KEY, "视频号账号"
            )["id"]
        else:
            account_id = existing["id"]
        self.account_service.repository.update(
            account_id, {"storage_state": storage_state, "status": "active"}
        )

    def clear(self) -> dict:
        account = self.account_service.repository.find_by_key("channels", ACCOUNT_KEY)
        if account is None:
            return {"deleted": False}
        self.account_service.repository.delete(account["id"])
        return {"deleted": True}

    # ---- 资料与作品 ----

    async def refresh(self) -> dict:
        """拉取资料 + 作品快照入库；返回 {ok, nickname, works_count, error?}。"""
        fetcher = self._fetcher()
        profile_result = await fetcher.fetch_profile()
        if not profile_result.get("ok"):
            return {"ok": False, "error": profile_result.get("error", "资料拉取失败"),
                    "logged_out": profile_result.get("logged_out", False)}
        self.store.save_profile(profile_result["profile"])

        works_result = await fetcher.fetch_works()
        if not works_result.get("ok"):
            return {"ok": False, "error": works_result.get("error", "作品拉取失败"),
                    "logged_out": works_result.get("logged_out", False), "nickname": profile_result["profile"].get("nickname")}
        self.store.save_works(works_result["works"])
        return {
            "ok": True,
            "nickname": profile_result["profile"].get("nickname", ""),
            "works_count": len(works_result["works"]),
        }

    def profile(self) -> dict | None:
        return self.store.get_profile()

    def works(self) -> list[dict]:
        return self.store.list_works()


# ---- API ----


@router.get("/status")
def status(service: ChannelsService = Depends(get_channels_service)) -> dict:
    return service.status()


@router.post("/qr-login")
async def qr_login_start(service: ChannelsService = Depends(get_channels_service)) -> dict:
    try:
        return await service.qr_start()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/qr-login/{session_id}")
def qr_login_poll(session_id: str, service: ChannelsService = Depends(get_channels_service)) -> dict:
    return service.qr_poll(session_id)


@router.delete("/qr-login/{session_id}")
def qr_login_cancel(session_id: str, service: ChannelsService = Depends(get_channels_service)) -> dict:
    return service.qr_cancel(session_id)


@router.delete("/account")
def clear_account(service: ChannelsService = Depends(get_channels_service)) -> dict:
    return service.clear()


@router.post("/refresh")
async def refresh(service: ChannelsService = Depends(get_channels_service)) -> dict:
    try:
        return await service.refresh()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/profile")
def profile(service: ChannelsService = Depends(get_channels_service)) -> dict:
    return {"profile": service.profile()}


@router.get("/works")
def works(service: ChannelsService = Depends(get_channels_service)) -> dict:
    return {"works": service.works()}
