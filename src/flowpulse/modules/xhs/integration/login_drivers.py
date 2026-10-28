"""Stateful login drivers wrapping the ported XHS login flows.

Each driver owns a live login-api object (curl_cffi session + mutable cookie
state) for one interactive login attempt. They are held in memory by the
service between the ``start`` and ``poll``/``verify`` HTTP calls.

The public high-level flows in the ported code block on a poll loop and read
the SMS code from ``input()``, which cannot be exposed over HTTP. These drivers
therefore replicate the exact request sequence from those flows step by step.
"""
from __future__ import annotations

from typing import Protocol


class LoginDriver(Protocol):
    platform: str

    def start_qrcode(self) -> str | None: ...

    def poll_qrcode(self) -> tuple[str, str, str | None]: ...

    def start_phone(self, phone: str, zone: str = "86") -> str | None: ...

    def verify_phone(self, code: str) -> str: ...


class PcLoginDriver:
    platform = "pc"

    def __init__(self, proxies: dict | None = None):
        from flowpulse.modules.xhs.apis.xhs_pc_login_apis import XHSLoginApi

        self.login = XHSLoginApi(proxies=proxies)
        self.cookies: dict | None = None
        self.qr_id: str | None = None
        self.code: str | None = None
        self.phone: str | None = None
        self.zone: str = "86"

    def start_qrcode(self) -> str | None:
        cookies = self.login.generate_init_cookies()
        ok, msg, qr = self.login.generate_qrcode(cookies)
        if not ok:
            raise RuntimeError(msg)
        cookies = qr["cookies"]
        # Browser order: create QR -> first anonymous poll -> webprofile.
        pre_ok, _pre_msg, cookies = self.login.check_qrcode_status(
            qr["qr_id"], qr["code"], cookies
        )
        if pre_ok:
            raise RuntimeError("二维码在展示前已被确认，拒绝异常登录状态")
        self.login.ensure_webprofile(cookies)
        self.cookies = cookies
        self.qr_id = qr["qr_id"]
        self.code = qr["code"]
        return qr["qr_url"]

    def poll_qrcode(self) -> tuple[str, str, str | None]:
        ok, msg, self.cookies = self.login.check_qrcode_status(
            self.qr_id, self.code, self.cookies
        )
        if ok:
            ok2, user_info, self.cookies = self.login.get_user_info(self.cookies)
            if not ok2 or user_info.get("guest") is not False:
                return "error", "正式会话验证失败", None
            return "confirmed", "登录成功", self.login.cookies_to_str(self.cookies)
        status_map = {
            "请扫描二维码": "waiting",
            "请确认登录": "scanned",
            "二维码已过期": "expired",
        }
        return status_map.get(msg, "waiting"), msg, None

    def start_phone(self, phone: str, zone: str = "86") -> str | None:
        cookies = self.login.generate_init_cookies()
        self.login.ensure_webprofile(cookies)
        ok, msg, _ = self.login.send_phone_code(phone, cookies, zone)
        if not ok:
            raise RuntimeError(msg)
        self.cookies = cookies
        self.phone = phone
        self.zone = zone
        return None

    def verify_phone(self, code: str) -> str:
        ok, msg, res = self.login.login_by_phone(self.phone, code, self.cookies, self.zone)
        if not ok:
            raise RuntimeError(msg)
        self.cookies = res["cookies"]
        return self.login.cookies_to_str(self.cookies)


class CreatorLoginDriver:
    platform = "creator"

    def __init__(self, proxies: dict | None = None):
        from flowpulse.modules.xhs.apis.xhs_creator_login_apis import XHSCreatorLoginApi

        self.login = XHSCreatorLoginApi(proxies=proxies)
        self.qr_id: str | None = None
        self.phone: str | None = None
        self.ready_cookie: str | None = None

    def _prepare(self):
        from flowpulse.modules.xhs.apis.xhs_creator_login_apis import LOGIN_SESSION_MAX_ATTEMPTS

        return LOGIN_SESSION_MAX_ATTEMPTS

    def start_qrcode(self) -> str | None:
        attempts = self._prepare()
        last_msg = "获取二维码失败"
        for _ in range(attempts):
            cookies, session = self.login._prepare_login_session()
            if session["active"]:
                accepted = self.login._accept_session(cookies)
                self.login._complete_security()
                self.ready_cookie = accepted
                return None
            self.login._complete_security()
            cookies = self.login.profile.cookie_map
            ok, msg, qr = self.login.generate_qrcode(cookies)
            if ok:
                self.qr_id = qr["qr_id"]
                return qr["qr_url"]
            last_msg = msg
            self.login._reset_anonymous_session()
        raise RuntimeError(last_msg)

    def poll_qrcode(self) -> tuple[str, str, str | None]:
        from flowpulse.modules.xhs.apis.xhs_creator_login_apis import (
            QR_STATUS_ERROR,
            QR_STATUS_EXPIRED,
            QR_STATUS_WAIT_CONFIRM,
            QR_STATUS_WAIT_SCAN,
        )

        detail = self.login.query_qrcode_status(self.qr_id)
        if detail["success"]:
            cookie_str = self.login._accept_session(detail["cookies"])
            if not cookie_str:
                return "error", "正式会话验证失败", None
            return "confirmed", "登录成功", cookie_str
        status = detail["status"]
        status_map = {
            QR_STATUS_WAIT_SCAN: "waiting",
            QR_STATUS_WAIT_CONFIRM: "scanned",
            QR_STATUS_EXPIRED: "expired",
            QR_STATUS_ERROR: "error",
        }
        return status_map.get(status, "waiting"), detail["message"], None

    def start_phone(self, phone: str, zone: str = "86") -> str | None:
        attempts = self._prepare()
        last_msg = "发送验证码失败"
        for _ in range(attempts):
            cookies, session = self.login._prepare_login_session()
            if session["active"]:
                accepted = self.login._accept_session(cookies)
                self.login._complete_security()
                self.ready_cookie = accepted
                return accepted
            self.login._complete_security()
            cookies = self.login.profile.cookie_map
            ok, msg, _ = self.login.send_phone_code(phone, cookies)
            if ok:
                self.phone = phone
                return None
            last_msg = msg
            self.login._reset_anonymous_session()
        raise RuntimeError(last_msg)

    def verify_phone(self, code: str) -> str:
        ok, msg, result = self.login.login_by_phone(self.phone, code)
        if not ok:
            raise RuntimeError(msg)
        return self.login._accept_session(result["cookies"])


def make_driver(platform: str, proxies: dict | None = None) -> LoginDriver:
    if platform == "pc":
        return PcLoginDriver(proxies)
    if platform == "creator":
        return CreatorLoginDriver(proxies)
    raise ValueError(f"unsupported platform: {platform}")
