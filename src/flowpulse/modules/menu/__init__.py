"""侧栏菜单模块：数据驱动（数据库/文件双模式存储），默认种子 + 整体替换保存。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.db.models import AppMenuRow

router = APIRouter()

# 与原前端写死菜单一一对应的默认种子；首次访问空库/空文件时自动写入
DEFAULT_MENUS: list[dict] = [
    {"id": "dashboard", "title": "驾驶舱", "path": "/dashboard", "icon": "Odometer"},
    {"id": "accounts", "title": "账号管理", "path": "/accounts", "icon": "Connection"},
    {"id": "messages", "title": "消息中心", "path": "/messages", "icon": "ChatDotRound"},
    {"id": "topics", "title": "选题管理", "path": "/topics", "icon": "Calendar"},
    {"id": "materials", "title": "素材库", "path": "/materials", "icon": "FolderOpened"},
    {"id": "weread", "title": "公众号订阅", "path": "/weread", "icon": "Reading"},
    {"id": "xhs", "title": "小红书工作台", "path": "/xhs", "icon": "PictureFilled"},
    {"id": "xhs-monitor", "title": "作品监控", "path": "/xhs/monitor", "icon": "Monitor"},
    {"id": "channels", "title": "视频号", "path": "/channels", "icon": "VideoCameraFilled"},
    {"id": "transcribe", "title": "转写任务", "path": "/transcribe", "icon": "VideoPlay"},
    {"id": "content-create", "title": "内容创作", "path": "/content/create", "icon": "EditPen"},
    {"id": "publish", "title": "发布任务", "path": "/publish", "icon": "Promotion"},
    {"id": "reports", "title": "数据报表", "path": "/reports/content", "icon": "DataAnalysis"},
    {"id": "reports-content", "title": "内容大盘", "path": "/reports/content", "parent": "reports"},
    {"id": "reports-ads", "title": "投流大盘", "path": "/reports/ads", "parent": "reports"},
    {"id": "settings", "title": "系统设置", "path": "/settings", "icon": "Setting"},
]


class MenuItemIn(BaseModel):
    id: str = Field(default="", max_length=64)
    title: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=128)
    icon: str = Field(default="", max_length=64)
    parent: str = Field(default="", max_length=64)
    visible: bool = True


class MenusUpdateRequest(BaseModel):
    menus: list[MenuItemIn]


class MenuRepository:
    """菜单存储：DATABASE_URL 模式走 app_menus 表，否则 data/app/menus.json。"""

    def __init__(self, sessionmaker_: sessionmaker[Session] | None, json_path: Path):
        self._sessionmaker = sessionmaker_
        self._json_path = json_path
        self._json_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- 读取 ----

    def list_menus(self) -> list[dict]:
        menus = self._load()
        if not menus:
            self.replace_all(DEFAULT_MENUS)
            menus = self._load()
        return menus

    def _load(self) -> list[dict]:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                rows = session.execute(
                    select(AppMenuRow).order_by(AppMenuRow.sort_order)
                ).scalars().all()
                return [
                    {
                        "id": row.id, "title": row.title, "path": row.path,
                        "icon": row.icon, "parent": row.parent or "",
                        "sort_order": row.sort_order, "visible": row.visible,
                    }
                    for row in rows
                ]
        data = read_json(self._json_path, {})
        return data.get("menus", [])

    # ---- 写入（整体替换，事务语义简单可靠） ----

    def replace_all(self, items: list[dict]) -> None:
        normalized = []
        for index, item in enumerate(items):
            item_id = (item.get("id") or "").strip() or f"m{index}"
            normalized.append(
                {
                    "id": item_id,
                    "title": item["title"],
                    "path": item["path"],
                    "icon": item.get("icon", ""),
                    "parent": item.get("parent", "") or "",
                    "sort_order": index,
                    "visible": bool(item.get("visible", True)),
                }
            )
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                session.execute(sa_delete(AppMenuRow))
                session.add_all([AppMenuRow(**row) for row in normalized])
                session.commit()
        else:
            atomic_write_json(self._json_path, {"menus": normalized})

    def reset_defaults(self) -> list[dict]:
        self.replace_all(DEFAULT_MENUS)
        return self._load()


def get_menu_repository() -> MenuRepository:
    raise RuntimeError("Dependency override is not configured")


@router.get("/api/menus")
def list_menus(repo: MenuRepository = Depends(get_menu_repository)) -> dict:
    return {"menus": repo.list_menus()}


@router.put("/api/menus")
def update_menus(
    request: MenusUpdateRequest, repo: MenuRepository = Depends(get_menu_repository)
) -> dict:
    items = [item.model_dump() for item in request.menus]
    repo.replace_all(items)
    return {"menus": repo.list_menus()}


@router.post("/api/menus/reset")
def reset_menus(repo: MenuRepository = Depends(get_menu_repository)) -> dict:
    return {"menus": repo.reset_defaults()}
