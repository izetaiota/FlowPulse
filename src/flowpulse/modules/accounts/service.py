"""账号中心服务：统一账号列表 = builtin（各模块提供方同步）+ managed（手工维护）。

builtin 行的凭证仍由所属模块存储（单一事实源），本层只聚合元数据与体检状态；
删除/体检动作路由回所属模块执行，保证与模块自身行为一致（如 weread 删除时清浏览器 profile）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from flowpulse.core.crypto import CredentialCipher
from flowpulse.modules.accounts.store import AccountRepository


@dataclass
class AccountSnapshot:
    """模块提供方上报的单账号快照（本地读取，不发网络请求）。"""

    account_key: str
    name: str = ""
    status: str = "unknown"  # active | expired | unknown
    last_check_at: str | None = None
    last_check_ok: bool | None = None
    last_check_message: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class CheckResult:
    ok: bool
    message: str
    extra: dict = field(default_factory=dict)


class BuiltinAccountProvider(Protocol):
    """模块接入账号中心的协议（P0 收编 weread/xhs，后续平台照此实现）。"""

    platform: str

    def enumerate(self) -> list[AccountSnapshot]:
        """枚举该模块当前已配置的账号（纯本地读取）。"""
        ...

    async def check(self, account_key: str) -> CheckResult:
        """在线体检一个账号（可发网络请求）。"""
        ...

    async def remove(self, account_key: str) -> bool:
        """删除模块内凭证（含关联清理，如浏览器 profile）。"""
        ...


# ---- weread 提供方：单凭证（default），凭证与体检状态来自 weread 模块仓储 ----


class WereadProvider:
    platform = "weread"

    def __init__(self, repository, service, qr_login) -> None:
        self._repository = repository
        self._service = service
        self._qr_login = qr_login

    def enumerate(self) -> list[AccountSnapshot]:
        state = self._repository.get_credential()
        if state is None:
            return []
        status = "unknown" if state.valid is None else ("active" if state.valid else "expired")
        return [
            AccountSnapshot(
                account_key="default",
                name="微信读书账号",
                status=status,
                last_check_at=state.last_validated_at,
                last_check_ok=state.valid,
                last_check_message=state.last_error,
                extra={"saved_at": state.saved_at, "module": "weread"},
            )
        ]

    async def check(self, account_key: str) -> CheckResult:
        try:
            result = await self._service.validate_current_credential()
        except Exception as exc:  # noqa: BLE001 - weread 校验失败以结果形式返回，不向调用方抛
            return CheckResult(ok=False, message=str(exc)[:200])
        return CheckResult(
            ok=bool(result.get("valid")),
            message=result.get("message", ""),
            extra={"book_count": result.get("book_count", 0)},
        )

    async def remove(self, account_key: str) -> bool:
        deleted = self._repository.delete_credential()
        # 与 weread 模块删除接口保持一致：同时清除浏览器登录态，防止每日续期"复活"凭证
        if deleted:
            clear = getattr(self._qr_login, "clear_profile", None)
            if clear is not None:
                try:
                    await clear()
                except Exception:  # noqa: BLE001 - profile 清理失败不阻塞删除
                    pass
        return deleted


# ---- xhs 提供方：pc / creator 双账号，体检状态复用凭证校验器的缓存 ----


class XhsProvider:
    platform = "xhs"
    PLATFORM_KEYS = ("pc", "creator")

    def __init__(self, service, credential_checker) -> None:
        self._service = service
        self._checker = credential_checker

    def _cached_result(self) -> dict:
        try:
            state = self._checker.status(populate=False)
        except Exception:  # noqa: BLE001 - 缓存缺失时按未知处理
            return {}
        return state.get("last_result") or {}

    def enumerate(self) -> list[AccountSnapshot]:
        cached = self._cached_result()
        try:
            last_run_at = self._checker.status(populate=False).get("last_run_at")
        except Exception:  # noqa: BLE001
            last_run_at = None
        snapshots: list[AccountSnapshot] = []
        for platform_key in self.PLATFORM_KEYS:
            try:
                cookie = self._service.cookies.get(platform_key)
            except Exception:  # noqa: BLE001
                cookie = None
            if not cookie:
                continue
            entry = cached.get(platform_key) or {}
            logged_in = entry.get("logged_in")
            status = "unknown" if logged_in is None else ("active" if logged_in else "expired")
            snapshots.append(
                AccountSnapshot(
                    account_key=platform_key,
                    name=f"小红书{'主站' if platform_key == 'pc' else '创作平台'}",
                    status=status,
                    last_check_at=last_run_at if logged_in is not None else None,
                    last_check_ok=logged_in,
                    last_check_message=entry.get("message", ""),
                    extra={"user_id": entry.get("user_id") or "", "module": "xhs"},
                )
            )
        return snapshots

    async def check(self, account_key: str) -> CheckResult:
        try:
            status = await self._service.login_status(account_key)
        except Exception as exc:  # noqa: BLE001
            return CheckResult(ok=False, message=str(exc)[:200])
        return CheckResult(
            ok=status.logged_in,
            message=status.message,
            extra={"user_id": status.user_id or ""},
        )

    async def remove(self, account_key: str) -> bool:
        existed = bool(self._service.cookies.get(account_key))
        self._service.cookies.clear(account_key)
        self._service.invalidate(account_key)
        return existed


# ---- 平台元数据（前端筛选与"手动账号"候选） ----

PLATFORM_LABELS: dict[str, str] = {
    "weread": "公众号（微信读书）",
    "xhs": "小红书",
    "douyin": "抖音",
    "kuaishou": "快手",
    "channels": "视频号",
    "tiktok": "TikTok",
}

BUILTIN_PLATFORMS = ("weread", "xhs")
# 允许手工登记账号的平台（P3+ 浏览器层落地前的占位登记）
MANAGED_PLATFORMS = ("douyin", "kuaishou", "channels", "tiktok")


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        providers: list[BuiltinAccountProvider] | None = None,
        cipher: CredentialCipher | None = None,
    ) -> None:
        self.repository = repository
        self.providers: dict[str, BuiltinAccountProvider] = {
            p.platform: p for p in (providers or [])
        }
        self.cipher = cipher

    # ---- 元数据 ----

    def platforms(self) -> list[dict]:
        builtin_keys = set(self.providers)
        return [
            {
                "id": pid,
                "label": PLATFORM_LABELS.get(pid, pid),
                "builtin": pid in builtin_keys or pid in BUILTIN_PLATFORMS,
                "managed": pid in MANAGED_PLATFORMS,
            }
            for pid in (*BUILTIN_PLATFORMS, *MANAGED_PLATFORMS)
        ]

    # ---- 列表（先同步 builtin 快照） ----

    def list_accounts(self, platform: str | None = None) -> list[dict]:
        self.sync_builtin()
        accounts = self.repository.list_accounts(platform)
        for account in accounts:
            account.pop("credential_encrypted", None)  # 列表永不外泄凭证
            account.pop("storage_state", None)
        return accounts

    def sync_builtin(self) -> None:
        """把各模块当前凭证状态同步进 fp_accounts；模块内凭证已删除的行一并移除。"""
        seen: set[tuple[str, str]] = set()
        for platform, provider in self.providers.items():
            try:
                snapshots = provider.enumerate()
            except Exception:  # noqa: BLE001 - 单模块同步失败不影响整体列表
                continue
            for snapshot in snapshots:
                self.repository.upsert_builtin(
                    platform,
                    snapshot.account_key,
                    {
                        "name": snapshot.name,
                        "status": snapshot.status,
                        "last_check_at": snapshot.last_check_at,
                        "last_check_ok": snapshot.last_check_ok,
                        "last_check_message": snapshot.last_check_message,
                        "extra": snapshot.extra,
                    },
                )
                seen.add((platform, snapshot.account_key))
        for row in self.repository.list_accounts():
            if row["kind"] == "builtin" and (row["platform"], row["account_key"]) not in seen:
                self.repository.delete(row["id"])

    # ---- 体检 ----

    async def check_account(self, account_id: int) -> dict:
        account = self.repository.get(account_id)
        if account is None:
            raise KeyError(f"账号不存在：{account_id}")
        if account["kind"] != "builtin":
            return {
                "account": account,
                "ok": None,
                "message": "手动登记的账号暂不支持在线体检（待浏览器登录层落地）",
            }
        provider = self.providers.get(account["platform"])
        if provider is None:
            raise ValueError(f"平台未接入：{account['platform']}")
        result: CheckResult = await provider.check(account["account_key"])
        updated = self.repository.update(
            account_id,
            {
                "status": "active" if result.ok else "expired",
                "last_check_ok": result.ok,
                "last_check_message": result.message[:500],
                "extra": {**(account.get("extra") or {}), **result.extra},
            },
        )
        return {"account": updated, "ok": result.ok, "message": result.message}

    # ---- managed 账号 CRUD ----

    def create_managed(
        self,
        platform: str,
        account_key: str,
        name: str,
        credential: str = "",
        storage_state: dict | None = None,
    ) -> dict:
        if platform not in MANAGED_PLATFORMS:
            raise ValueError(f"平台不支持手工登记：{platform}")
        credential_encrypted = None
        if credential.strip():
            if self.cipher is None or not self.cipher.available:
                raise ValueError("凭证加密不可用（未安装 cryptography），拒绝保存明文")
            credential_encrypted = self.cipher.encrypt(credential.strip())
        account = self.repository.create_managed(
            platform, account_key, name, credential_encrypted, storage_state
        )
        account.pop("credential_encrypted", None)
        return account

    def update_managed(self, account_id: int, name: str | None, status: str | None) -> dict:
        account = self.repository.get(account_id)
        if account is None:
            raise KeyError(f"账号不存在：{account_id}")
        if account["kind"] != "managed":
            raise ValueError("内置模块账号请在所属模块页面管理")
        updates: dict[str, Any] = {}
        if name is not None and name.strip():
            updates["name"] = name.strip()
        if status is not None:
            if status not in ("active", "disabled", "unknown"):
                raise ValueError(f"非法状态：{status}")
            updates["status"] = status
        updated = self.repository.update(account_id, updates)
        updated.pop("credential_encrypted", None)
        return updated

    def get_credential(self, account_id: int) -> str | None:
        """解密取回 managed 账号凭证（浏览器层/后续平台驱动使用）。"""
        account = self.repository.get(account_id)
        if account is None or not account.get("credential_encrypted"):
            return None
        if self.cipher is None or not self.cipher.available:
            return None
        try:
            return self.cipher.decrypt(account["credential_encrypted"])
        except Exception:  # noqa: BLE001 - 密钥不符等
            return None

    # ---- 删除 ----

    async def delete_account(self, account_id: int) -> dict:
        account = self.repository.get(account_id)
        if account is None:
            raise KeyError(f"账号不存在：{account_id}")
        module_deleted = False
        if account["kind"] == "builtin":
            provider = self.providers.get(account["platform"])
            if provider is None:
                raise ValueError(f"平台未接入：{account['platform']}")
            module_deleted = await provider.remove(account["account_key"])
        row_deleted = self.repository.delete(account_id)
        return {"deleted": row_deleted, "module_credential_cleared": module_deleted}
