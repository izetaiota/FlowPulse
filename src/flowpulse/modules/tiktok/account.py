"""TikTok 账号接入（T5.3）：仅 Cookie 导入（sessionid 关键字段），无浏览器扫码。"""

from __future__ import annotations

class TiktokAccountService:
    """TikTok 账号：仅 Cookie 导入（sessionid 关键字段），无浏览器扫码。"""

    def __init__(self, account_service):
        self.account_service = account_service

    def status(self) -> dict:
        account = self.account_service.repository.find_by_key("tiktok", "default")
        has_cookie = False
        if account:
            credential = self.account_service.get_credential(account["id"]) or ""
            has_cookie = "sessionid=" in credential
        return {
            "configured": account is not None,
            "logged_in_guess": has_cookie,
            "note": "TikTok 搜索匿名可用，导入 Cookie 更稳（需含 sessionid）",
        }

    def import_cookie(self, cookie: str) -> dict:
        cookie = (cookie or "").strip()
        if not cookie:
            raise ValueError("Cookie 不能为空")
        existing = self.account_service.repository.find_by_key("tiktok", "default")
        cipher = self.account_service.cipher
        if cipher is None or not cipher.available:
            raise ValueError("凭证加密不可用（未安装 cryptography），拒绝保存明文")
        if existing is None:
            account = self.account_service.repository.create_managed(
                "tiktok", "default", "TikTok 账号", credential_encrypted=cipher.encrypt(cookie)
            )
        else:
            account = self.account_service.repository.update(
                existing["id"], {"credential_encrypted": cipher.encrypt(cookie), "status": "active"}
            )
        return {"account_id": account["id"], "configured": True}

    def clear(self) -> dict:
        account = self.account_service.repository.find_by_key("tiktok", "default")
        if account is None:
            return {"deleted": False}
        self.account_service.repository.delete(account["id"])
        return {"deleted": True}
