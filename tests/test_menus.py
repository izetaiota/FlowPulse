"""菜单模块测试：默认种子、整体替换、恢复默认、API 行为（文件模式）。"""

from pathlib import Path

from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.menu import DEFAULT_MENUS, MenuRepository


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        transcribe_engine="mock",
        weread_request_interval_seconds=0,
        weread_sync_interval_minutes=0,
        weread_cookie_refresh_hours=0,
        xhs_credential_check_minutes=0,
    )


def test_menu_repo_seeds_defaults(tmp_path: Path):
    repo = MenuRepository(None, tmp_path / "app" / "menus.json")
    menus = repo.list_menus()
    assert [m["title"] for m in menus][:3] == ["驾驶舱", "账号管理", "消息中心"]
    assert len(menus) == len(DEFAULT_MENUS)
    # 子菜单挂到父级
    reports = next(m for m in menus if m["id"] == "reports")
    children = [m for m in menus if m["parent"] == "reports"]
    assert reports and len(children) == 2


def test_menu_repo_replace_and_reset(tmp_path: Path):
    repo = MenuRepository(None, tmp_path / "app" / "menus.json")
    repo.replace_all([{"title": "自定义", "path": "/custom", "icon": "Star", "visible": True}])
    menus = repo.list_menus()
    assert len(menus) == 1 and menus[0]["title"] == "自定义"

    reset = repo.reset_defaults()
    assert len(reset) == len(DEFAULT_MENUS)


def test_menu_repo_db_mode_roundtrip(tmp_path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from flowpulse.db.engine import ensure_tables

    engine = create_engine(f"sqlite:///{tmp_path}/db.sqlite", future=True)
    ensure_tables(engine)
    repo = MenuRepository(
        sessionmaker(bind=engine, expire_on_commit=False, future=True),
        tmp_path / "app" / "menus.json",
    )
    assert len(repo.list_menus()) == len(DEFAULT_MENUS)
    repo.replace_all([{"title": "X", "path": "/x", "visible": True}])
    assert repo.list_menus()[0]["title"] == "X"


def test_menu_api_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("flowpulse.config.get_settings", lambda: make_settings(tmp_path))
    monkeypatch.setattr("flowpulse.main.get_settings", lambda: make_settings(tmp_path))
    with TestClient(create_app()) as client:
        menus = client.get("/api/menus").json()["menus"]
        assert len(menus) == len(DEFAULT_MENUS)

        # 整体替换 → 再恢复默认
        saved = client.put(
            "/api/menus",
            json={"menus": [{"title": "仅一个", "path": "/one", "icon": "Star", "visible": True}]},
        ).json()["menus"]
        assert len(saved) == 1

        restored = client.post("/api/menus/reset").json()["menus"]
        assert len(restored) == len(DEFAULT_MENUS)
