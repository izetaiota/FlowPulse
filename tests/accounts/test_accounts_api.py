"""账号中心 API 测试（文件模式，鉴权关闭）：列表/平台元数据/managed CRUD/体检/删除。"""

from pathlib import Path

from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
    )


def make_client(tmp_path: Path, monkeypatch) -> TestClient:
    settings = make_settings(tmp_path)
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: settings)
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: settings)
    return TestClient(create_app())


def test_list_platforms_and_empty_accounts(tmp_path: Path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    platforms = client.get("/api/v1/accounts/platforms").json()["platforms"]
    ids = [p["id"] for p in platforms]
    assert "weread" in ids and "xhs" in ids and "douyin" in ids
    assert all("label" in p for p in platforms)

    # 空库：无 weread/xhs 凭证时列表为空（不出现幽灵行）
    accounts = client.get("/api/v1/accounts").json()["accounts"]
    assert accounts == []


def test_managed_account_crud_flow(tmp_path: Path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    # 创建（无凭证的占位登记；带明文凭证在未装 cryptography 时会 400，跳过该路径）
    resp = client.post(
        "/api/v1/accounts",
        json={"platform": "douyin", "account_key": "sec_demo", "name": "抖音演示号"},
    )
    assert resp.status_code == 201
    account = resp.json()
    assert account["kind"] == "managed" and "credential_encrypted" not in account

    # 重复创建 400
    assert client.post(
        "/api/v1/accounts",
        json={"platform": "douyin", "account_key": "sec_demo", "name": "重复"},
    ).status_code == 400

    # 平台过滤生效
    assert client.get("/api/v1/accounts", params={"platform": "xhs"}).json()["accounts"] == []

    # 更新
    resp = client.patch(f"/api/v1/accounts/{account['id']}", json={"name": "新名字"})
    assert resp.json()["name"] == "新名字"

    # 体检：managed 账号返回"暂不支持"
    check = client.post(f"/api/v1/accounts/{account['id']}/check").json()
    assert check["ok"] is None

    # 删除
    assert client.delete(f"/api/v1/accounts/{account['id']}").json()["deleted"] is True
    assert client.get("/api/v1/accounts").json()["accounts"] == []


def test_builtin_weread_account_appears_after_credential(tmp_path: Path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    # 直接向 weread 仓储写入凭证（绕过网络校验），账号中心同步后应出现 builtin 行
    from flowpulse.modules.weread.models import CredentialState

    weread_service = client.app.state.weread_service
    weread_service.repository.update_credential(
        CredentialState(cookie="wr_vid=1; wr_skey=abc", valid=True, last_error="")
    )

    accounts = client.get("/api/v1/accounts", params={"platform": "weread"}).json()["accounts"]
    assert len(accounts) == 1
    assert accounts[0]["platform"] == "weread" and accounts[0]["kind"] == "builtin"
    assert accounts[0]["status"] == "active"
