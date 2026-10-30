"""账号中心存储测试：文件模式 + sqlite（PG 模式同构）双后端。"""

from pathlib import Path

from flowpulse.modules.accounts.store import AccountRepository


def test_file_mode_builtin_upsert_and_managed_crud(tmp_path: Path):
    repo = AccountRepository(None, tmp_path / "accounts" / "accounts.json")

    # builtin 同步：插入 → 更新
    row = repo.upsert_builtin(
        "weread", "default", {"name": "微信读书账号", "status": "active", "extra": {"a": 1}}
    )
    assert row["kind"] == "builtin" and row["status"] == "active"
    again = repo.upsert_builtin(
        "weread", "default", {"name": "微信读书账号", "status": "expired", "extra": {"b": 2}}
    )
    assert again["id"] == row["id"] and again["status"] == "expired"
    assert again["extra"] == {"a": 1, "b": 2}  # extra 合并不覆盖
    assert len(repo.list_accounts()) == 1

    # managed：创建 / 唯一约束 / 更新 / 删除
    managed = repo.create_managed("douyin", "sec_uid_x", "测试抖音号", credential_encrypted="cipher")
    assert managed["kind"] == "managed"
    try:
        repo.create_managed("douyin", "sec_uid_x", "重复")
    except ValueError:
        pass
    else:
        raise AssertionError("同 platform+account_key 应拒绝重复创建")

    updated = repo.update(managed["id"], {"name": "改名", "status": "disabled"})
    assert updated["name"] == "改名" and updated["status"] == "disabled"

    assert repo.delete(managed["id"]) is True
    assert repo.get(managed["id"]) is None
    assert repo.delete(managed["id"]) is False

    # 平台筛选
    assert [a["account_key"] for a in repo.list_accounts(platform="weread")] == ["default"]
    assert repo.list_accounts(platform="douyin") == []


def test_sqlite_mode_roundtrip(tmp_path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from flowpulse.db.engine import ensure_tables

    engine = create_engine(f"sqlite:///{tmp_path}/db.sqlite", future=True)
    ensure_tables(engine)
    sessionmaker_ = sessionmaker(engine, future=True)

    repo = AccountRepository(sessionmaker_, tmp_path / "accounts" / "accounts.json")
    repo.upsert_builtin("xhs", "pc", {"name": "小红书主站", "status": "active"})
    repo.upsert_builtin("xhs", "creator", {"name": "小红书创作平台", "status": "unknown"})
    managed = repo.create_managed("tiktok", "user_1", "TikTok 测试")

    rows = repo.list_accounts()
    assert len(rows) == 3
    assert all(r["last_check_at"] is None or isinstance(r["last_check_at"], str) for r in rows)

    # builtin 与 managed 均可按 id 更新与删除
    repo.update(managed["id"], {"last_check_message": "手动账号暂不支持体检"})
    assert repo.get(managed["id"])["last_check_message"] == "手动账号暂不支持体检"
    assert repo.delete(managed["id"]) is True
    assert len(repo.list_accounts()) == 2
