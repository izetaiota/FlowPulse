"""快手账号接入（T5.1）：Cookie 粘贴导入 + 浏览器扫码登录（镜像抖音账号模式）。

快手登录 Cookie 关键字段：userId + passToken；账号落在 fp_accounts（platform=kuaishou）。
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
from flowpulse.modules.ks.browser import has_ks_login_cookie, ks_cookie_storage_state

ACCOUNT_KEY = "default"
QR_TIMEOUT_SECONDS = 300
KS_HOME = "https://www.kuaishou.com/"


class KsAccountService:
    def __init__(self, account_service: AccountService, profiles_root) -> None:
        self.account_service = account_service
        self.allocator = ProfileAllocator(profiles_root)
        self.sessions: dict[str, dict[str, Any]] = {}

    def status(self) -> dict:
        account = self.account_service.repository.find_by_key("kuaishou", ACCOUNT_KEY)
        has_cookie = False
        if account:
            credential = self.account_service.get_credential(account["id"])
            has_cookie = has_ks_login_cookie(credential or "")
        return {
            "configured": account is not None,
            "logged_in_guess": has_cookie,
            "engine": browser_engine.browser_engine_name(),
            "account_id": account["id"] if account else None,
        }

    def import_cookie(self, cookie: str) -> dict:
        cookie = (cookie or "").strip()
        if not has_ks_login_cookie(cookie):
            raise ValueError("Cookie 不完整：至少需要包含 userId 与 passToken 两个字段")
        existing = self.account_service.repository.find_by_key("kuaishou", ACCOUNT_KEY)
        if existing is None:
            account = self.account_service.create_managed(
                "kuaishou", ACCOUNT_KEY, "快手账号", credential=cookie
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
        account = self.account_service.repository.find_by_key("kuaishou", ACCOUNT_KEY)
        if account is None:
            return {"deleted": False}
        self.account_service.repository.delete(account["id"])
        return {"deleted": True}

    # ---- 扫码登录（有头浏览器，轮询 cookie） ----

    async def qr_start(self) -> dict:
        if browser_engine.browser_engine_name() == "none":
            raise RuntimeError("未安装浏览器引擎：pip install -e \".[browser]\" 或 pip install playwright")
        session_id = uuid.uuid4().hex
        state = LoginSessionState(platform="kuaishou", account_key=ACCOUNT_KEY)
        state.transition(LoginDriverState.WAITING, "已打开快手首页，请在浏览器中登录（扫码）")
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
            state.transition(LoginDriverState.EXPIRED, "登录超时，请重新发起")
        result = {"session_id": session_id, "state": state.state.value, "message": state.message}
        if state.state in (
            LoginDriverState.LOGGED_IN,
            LoginDriverState.FAILED,
            LoginDriverState.CANCELLED,
            LoginDriverState.EXPIRED,
        ):
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
        profile = self.allocator.allocate("ks", "qr-login")
        context = None
        try:
            context = await browser_engine.launch_persistent_context(profile, headless=False)
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(KS_HOME, wait_until="domcontentloaded")
            deadline = time.monotonic() + QR_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                await asyncio.sleep(2)
                cookies = await context.cookies(["https://www.kuaishou.com/"])
                cookie = "; ".join(
                    f"{c['name']}={c['value']}" for c in cookies if "kuaishou.com" in (c.get("domain") or "")
                )
                if has_ks_login_cookie(cookie):
                    storage = {"cookies": [c for c in cookies if "kuaishou.com" in (c.get("domain") or "")], "origins": []}
                    self._persist_login(cookie, storage)
                    state.transition(LoginDriverState.LOGGED_IN, "登录成功，账号已保存")
                    return
                if self.sessions.get(session_id) is None:
                    return
            state.transition(LoginDriverState.EXPIRED, "登录超时，请重新发起")
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

    def _persist_login(self, cookie: str, storage_state: dict) -> None:
        existing = self.account_service.repository.find_by_key("kuaishou", ACCOUNT_KEY)
        account_id = (
            existing["id"]
            if existing
            else self.account_service.repository.create_managed(
                "kuaishou", ACCOUNT_KEY, "快手账号"
            )["id"]
        )
        self._save_credential(account_id, cookie)
        self.account_service.repository.update(account_id, {"storage_state": storage_state})
