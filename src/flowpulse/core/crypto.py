"""凭证静态加密（Fernet）：文件存储与数据库存储共用的加密封装。

密钥来源优先级：外部密钥（WEREAD_CREDENTIAL_KEY 等）> 密钥文件（自动生成）。
未安装 cryptography 时降级为明文（功能不受影响，仅静态保护缺失）。
"""

from __future__ import annotations

from pathlib import Path


class CredentialCipher:
    def __init__(self, credential_key: str = "", key_file: Path | None = None):
        self._fernet = None
        self._invalid_token: type[Exception] | None = None
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError:
            return
        self._invalid_token = InvalidToken
        key = (credential_key or "").strip()
        if key:
            # 外部密钥非法时直接报错，避免静默降级
            self._fernet = Fernet(key.encode())
            return
        if key_file is not None:
            try:
                key = key_file.read_text(encoding="utf-8").strip()
            except OSError:
                key = Fernet.generate_key().decode()
                key_file.write_text(key, encoding="utf-8")
            self._fernet = Fernet(key.encode())

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, text: str) -> str:
        return self._fernet.encrypt(text.encode()).decode()

    def decrypt(self, text: str) -> str:
        return self._fernet.decrypt(text.encode()).decode()

    def seal(self, payload: dict) -> dict:
        """加密字典里的 cookie 字段并打上 cookie_encrypted 标记。"""
        if self._fernet and payload.get("cookie"):
            payload = dict(payload)
            payload["cookie"] = self.encrypt(payload["cookie"])
            payload["cookie_encrypted"] = True
        return payload

    def unseal(self, data) -> dict | None:
        """解密封装；旧版明文原样返回（下次保存自动升级为加密）；密钥不符返回 None。"""
        if not data:
            return None
        if not data.get("cookie_encrypted"):
            return data
        if not self._fernet:
            return None
        try:
            data = dict(data)
            data["cookie"] = self.decrypt(data["cookie"])
        except Exception:
            return None
        data.pop("cookie_encrypted", None)
        return data
