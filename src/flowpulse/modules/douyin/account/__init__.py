"""抖音账号接入（T3.1）：Cookie 粘贴导入 + 浏览器扫码登录（start→poll→verify 状态机）。

账号落在统一账号中心（fp_accounts managed 行，platform=douyin/account_key=default）：
- credential（Fernet 加密）：完整 Cookie 串；
- storage_state：扫码登录成功后的浏览器登录态（fetcher 复用，免重复登录）。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from flowpulse.modules.accounts.service import AccountService
from flowpulse.modules.browser import (
    LoginDriverState,
    LoginSessionState,
    ProfileAllocator,
)
from flowpulse.modules.browser import engine as browser_engine

ACCOUNT_KEY = "default"
QR_TIMEOUT_SECONDS = 300  # 扫码有效期


class DouyinAccountService:
    def __init__(self, account_service: AccountService, profiles_root) -> None:
        self.account_service = account_service
        self.allocator = ProfileAllocator(profiles_root)
        self.sessions: dict[str, dict[str, Any]] = {}

    # ---- 状态查询 ----

    def status(self) -> dict:
        account = self.account_service.repository.find_by_key("douyin", ACCOUNT_KEY)
        has_cookie = False
        if account:
            credential = self.account_service.get_credential(account["id"])
            has_cookie = browser_engine.has_login_cookie(credential or "")
        return {
            "configured": account is not None,
            "logged_in_guess": has_cookie,
            "storage_state_available": bool(account and account.get("storage_state")),
            "engine": browser_engine.browser_engine_name(),
            "account_id": account["id"] if account else None,
        }

    # ---- Cookie 导入 ----

    def import_cookie(self, cookie: str) -> dict:
        cookie = (cookie or "").strip()
        if not browser_engine.has_login_cookie(cookie):
            raise ValueError("Cookie 不完整：至少需要包含 sessionid 与 ttwid 两个字段")
        existing = self.account_service.repository.find_by_key("douyin", ACCOUNT_KEY)
        if existing is None:
            account = self.account_service.create_managed(
                "douyin", ACCOUNT_KEY, "抖音账号", credential=cookie
            )
        else:
            account = self._save_credential(existing["id"], cookie)
        return {"account_id": account["id"], "configured": True}

    def _save_credential(self, account_id: int, cookie: str) -> dict:
        cipher = self.account_service.cipher
        if cipher is None or not cipher.available:
            raise ValueError("凭证加密不可用（未安装 cryptography），拒绝保存明文")
        return self.account_service.repository.update(
            account_id,
            {
                "credential_encrypted": cipher.encrypt(cookie),
                "status": "active",
                "last_check_message": "Cookie 导入（未校验）",
            },
        )

    def clear(self) -> dict:
        account = self.account_service.repository.find_by_key("douyin", ACCOUNT_KEY)
        if account is None:
            return {"deleted": False}
        self.account_service.repository.delete(account["id"])
        return {"deleted": True}

    # ---- 扫码登录（状态机） ----

    async def qr_start(self) -> dict:
        if browser_engine.browser_engine_name() == "none":
            raise RuntimeError("未安装浏览器引擎：pip install -e \".[browser]\" 或 pip install playwright")
        session_id = uuid.uuid4().hex
        state = LoginSessionState(platform="douyin", account_key=ACCOUNT_KEY)
        state.transition(LoginDriverState.WAITING, "已打开抖音首页，请在浏览器中扫码登录")
        self.sessions[session_id] = {"state": state, "started_at": time.monotonic()}
        task = asyncio.create_task(self._qr_worker(session_id))
        self.sessions[session_id]["task"] = task
        return {"session_id": session_id, "state": state.state.value, "message": state.message}

    def qr_poll(self, session_id: str) -> dict:
        entry = self.sessions.get(session_id)
        if entry is None:
            return {"session_id": session_id, "state": "unknown", "message": "会话不存在或已结束"}
        state: LoginSessionState = entry["state"]
        elapsed = time.monotonic() - entry["started_at"]
        if state.state == LoginDriverState.WAITING and elapsed > QR_TIMEOUT_SECONDS:
            state.transition(LoginDriverState.EXPIRED, "扫码超时，请重新发起")
        result = {
            "session_id": session_id,
            "state": state.state.value,
            "message": state.message,
        }
        # 终态后清理会话记录
        if state.state in (LoginDriverState.LOGGED_IN, LoginDriverState.FAILED, LoginDriverState.CANCELLED, LoginDriverState.EXPIRED):
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
            # 保留结果一小段时间供轮询读取；直接清理亦可（前端已拿到终态）
            self.sessions.pop(session_id, None)
        return result

    def qr_cancel(self, session_id: str) -> dict:
        entry = self.sessions.pop(session_id, None)
        if entry:
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
            entry["state"].transition(LoginDriverState.CANCELLED, "已取消")
            return {"cancelled": True}
        return {"cancelled": False}

    async def _qr_worker(self, session_id: str) -> None:
        """打开抖音首页等待用户扫码；轮询 context cookies，出现 sessionid 即成功。"""
        entry = self.sessions.get(session_id)
        if entry is None:
            return
        profile = self.allocator.allocate("douyin", "qr-login")
        state: LoginSessionState = entry["state"]
        context = None
        try:
            context = await browser_engine.launch_persistent_context(profile, headless=False)
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
            deadline = time.monotonic() + QR_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                await asyncio.sleep(2)
                cookies = await context.cookies(["https://www.douyin.com"])
                cookie = browser_engine.cookie_from_context_cookies(cookies)
                if browser_engine.has_login_cookie(cookie):
                    storage = {"cookies": cookies, "origins": []}
                    self._persist_login(cookie, storage)
                    state.transition(LoginDriverState.LOGGED_IN, "扫码登录成功，账号已保存")
                    return
                if self.sessions.get(session_id) is None:  # 已被取消
                    return
            state.transition(LoginDriverState.EXPIRED, "扫码超时，请重新发起")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 登录失败写入状态机
            state.transition(LoginDriverState.FAILED, f"登录失败：{exc}"[:200])
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:  # noqa: BLE001
                    pass

    def _persist_login(self, cookie: str, storage_state: dict) -> None:
        existing = self.account_service.repository.find_by_key("douyin", ACCOUNT_KEY)
        if existing is None:
            account = self.account_service.repository.create_managed(
                "douyin", ACCOUNT_KEY, "抖音账号"
            )
            account_id = account["id"]
        else:
            account_id = existing["id"]
        self._save_credential(account_id, cookie)
        self.account_service.repository.update(account_id, {"storage_state": storage_state})
