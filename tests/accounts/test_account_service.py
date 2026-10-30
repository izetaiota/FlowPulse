"""账号中心服务测试：builtin 提供方同步/体检/删除路由 + managed 凭证加解密。"""

from pathlib import Path

import pytest

from flowpulse.core.crypto import CredentialCipher
from flowpulse.modules.accounts.service import (
    AccountService,
    AccountSnapshot,
    CheckResult,
)
from flowpulse.modules.accounts.store import AccountRepository


class FakeProvider:
    platform = "fake"

    def __init__(self):
        self.accounts: dict[str, dict] = {"default": {"name": "假账号", "valid": True}}
        self.checked: list[str] = []
        self.removed: list[str] = []

    def enumerate(self) -> list[AccountSnapshot]:
        return [
            AccountSnapshot(
                account_key=key,
                name=value["name"],
                status="active" if value["valid"] else "expired",
                last_check_ok=value["valid"],
            )
            for key, value in self.accounts.items()
        ]

    async def check(self, account_key: str) -> CheckResult:
        self.checked.append(account_key)
        valid = self.accounts.get(account_key, {}).get("valid", False)
        return CheckResult(ok=valid, message="有效" if valid else "已失效")

    async def remove(self, account_key: str) -> bool:
        self.removed.append(account_key)
        return self.accounts.pop(account_key, None) is not None


def make_service(tmp_path: Path, providers=None, with_cipher=False) -> AccountService:
    repo = AccountRepository(None, tmp_path / "accounts" / "accounts.json")
    cipher = CredentialCipher(key_file=tmp_path / "accounts" / ".credential_key") if with_cipher else None
    return AccountService(repo, providers=providers, cipher=cipher)


@pytest.mark.asyncio
async def test_builtin_sync_add_and_prune(tmp_path: Path):
    provider = FakeProvider()
    service = make_service(tmp_path, providers=[provider])

    accounts = service.list_accounts()
    assert [a["account_key"] for a in accounts] == ["default"]
    assert accounts[0]["kind"] == "builtin"

    # 模块内凭证删除后，同步应移除对应行
    provider.accounts.clear()
    accounts = service.list_accounts()
    assert accounts == []


@pytest.mark.asyncio
async def test_check_updates_row(tmp_path: Path):
    provider = FakeProvider()
    service = make_service(tmp_path, providers=[provider])
    account_id = service.list_accounts()[0]["id"]

    provider.accounts["default"]["valid"] = False
    result = await service.check_account(account_id)
    assert result["ok"] is False and result["message"] == "已失效"
    assert result["account"]["status"] == "expired"
    assert provider.checked == ["default"]


@pytest.mark.asyncio
async def test_delete_routes_to_provider(tmp_path: Path):
    provider = FakeProvider()
    service = make_service(tmp_path, providers=[provider])
    account_id = service.list_accounts()[0]["id"]

    result = await service.delete_account(account_id)
    assert result == {"deleted": True, "module_credential_cleared": True}
    assert provider.removed == ["default"]


@pytest.mark.asyncio
async def test_managed_credential_roundtrip(tmp_path: Path):
    pytest.importorskip("cryptography")
    service = make_service(tmp_path, with_cipher=True)

    account = service.create_managed("douyin", "sec_1", "抖音号", credential="cookie abc")
    assert account["kind"] == "managed"
    assert "credential_encrypted" not in account  # 凭证不外泄
    # 底层确为密文
    raw = service.repository.get(account["id"])
    assert raw["credential_encrypted"] != "cookie abc"
    assert service.get_credential(account["id"]) == "cookie abc"

    # 重复登记拒绝；非 managed 平台拒绝
    with pytest.raises(ValueError):
        service.create_managed("douyin", "sec_1", "重复")
    with pytest.raises(ValueError):
        service.create_managed("weread", "x", "内置平台")


@pytest.mark.asyncio
async def test_managed_check_unsupported(tmp_path: Path):
    service = make_service(tmp_path, with_cipher=True)
    account = service.create_managed("kuaishou", "u1", "快手占位")
    result = await service.check_account(account["id"])
    assert result["ok"] is None and "暂不支持" in result["message"]
