"""统一账号中心模块（P0）：多平台账号聚合视图 + managed 账号登记。

builtin 账号（weread/xhs）由各模块提供方同步，凭证仍归属模块存储；
managed 账号凭证 Fernet 加密存 fp_accounts（P3+ 浏览器登录层启用）。
"""

from flowpulse.modules.accounts.routes import get_account_service, router
from flowpulse.modules.accounts.service import (
    AccountService,
    AccountSnapshot,
    BuiltinAccountProvider,
    CheckResult,
    WereadProvider,
    XhsProvider,
)
from flowpulse.modules.accounts.store import AccountRepository

__all__ = [
    "AccountRepository",
    "AccountService",
    "AccountSnapshot",
    "BuiltinAccountProvider",
    "CheckResult",
    "WereadProvider",
    "XhsProvider",
    "get_account_service",
    "router",
]
