"""抖音发布服务（T3.4）：草稿 CRUD + 串行发布队列 worker（浏览器有头执行）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from flowpulse.modules.browser import ProfileAllocator
from flowpulse.modules.douyin.publish import driver
from flowpulse.modules.douyin.publish.store import (
    STATUS_CANCELED,
    STATUS_DRAFT,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PUBLISHING,
    DouyinPublishStore,
)

WORKER_TICK_SECONDS = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DouyinPublishService:
    def __init__(
        self,
        store: DouyinPublishStore,
        data_root: Path,
        get_login_state,
        profiles_root: Path,
        enabled: bool = True,
    ):
        """data_root：媒体库根（解析 downloads/xxx 相对路径）；get_login_state 同 fetcher。"""
        self.store = store
        self.data_root = data_root
        self._get_login_state = get_login_state
        self.allocator = ProfileAllocator(profiles_root)
        self.enabled = enabled
        self._task: asyncio.Task | None = None
        self._busy = False

    # ---- 生命周期 ----

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.process_next()
            except Exception:  # noqa: BLE001 - 后台循环不允许中断
                pass
            await asyncio.sleep(WORKER_TICK_SECONDS)

    # ---- 草稿管理 ----

    def resolve_media_paths(self, media_paths: list[str]) -> list[str]:
        """媒体库相对路径（downloads/<task>/<file>）→ 绝对路径；越界的绝对路径直接拒绝。"""
        resolved = []
        for rel in media_paths:
            candidate = (self.data_root / rel).resolve()
            if self.data_root.resolve() not in candidate.parents:
                raise ValueError(f"非法媒体路径：{rel}")
            resolved.append(str(candidate))
        return resolved

    def list_media_files(self) -> list[dict]:
        """列出 downloads 下两层内的可发布媒体文件（相对路径 + 大小）。"""
        media_root = self.data_root / "downloads"
        if not media_root.is_dir():
            return []
        suffixes = {".mp4", ".mov", ".webm", ".mkv", ".flv", ".jpg", ".jpeg", ".png", ".webp"}
        entries = []
        for task_dir in sorted(media_root.iterdir()):
            if not task_dir.is_dir():
                continue
            for item in sorted(task_dir.iterdir()):
                if item.is_file() and item.suffix.lower() in suffixes:
                    entries.append(
                        {
                            "path": f"downloads/{task_dir.name}/{item.name}",
                            "name": item.name,
                            "size": item.stat().st_size,
                        }
                    )
        return entries

    def create_draft(self, fields: dict) -> dict:
        media_paths = list(fields.get("media_paths") or [])
        if not media_paths:
            raise ValueError("请至少选择一个媒体文件")
        self.resolve_media_paths(media_paths)  # 提前校验
        return self.store.create(fields)

    def submit(self, task_id: int) -> dict:
        task = self.store.get(task_id)
        if task is None:
            raise KeyError(f"任务不存在：{task_id}")
        if task["status"] not in (STATUS_DRAFT, STATUS_FAILED):
            raise ValueError(f"当前状态（{task['status']}）不可提交")
        return self.store.update(task_id, {"status": STATUS_PENDING, "error": ""})

    def cancel(self, task_id: int) -> dict:
        task = self.store.get(task_id)
        if task is None:
            raise KeyError(f"任务不存在：{task_id}")
        if task["status"] in (STATUS_PUBLISHING, STATUS_DONE, STATUS_CANCELED):
            raise ValueError(f"当前状态（{task['status']}）不可取消")
        return self.store.update(task_id, {"status": STATUS_CANCELED})

    def delete(self, task_id: int) -> bool:
        task = self.store.get(task_id)
        if task is None:
            return False
        if task["status"] == STATUS_PUBLISHING:
            raise ValueError("发布中的任务不可删除")
        return self.store.delete(task_id)

    # ---- 队列执行 ----

    async def process_next(self) -> dict | None:
        if self._busy:
            return None
        task = self.store.next_due(_now_iso())
        if task is None:
            return None
        self._busy = True
        try:
            self.store.update(task["id"], {"status": STATUS_PUBLISHING, "error": ""})
            cookie, storage_state = self._get_login_state()
            if storage_state is None and not cookie:
                return self.store.update(
                    task["id"],
                    {
                        "status": STATUS_FAILED,
                        "error": "未配置抖音账号：请先在「作品监控」页扫码登录或导入 Cookie",
                    },
                )
            files = self.resolve_media_paths(task["media_paths"])
            topics = " ".join(
                f"#{t.strip().lstrip('#')}" for t in (task.get("topics") or "").split(",") if t.strip()
            )
            body = ((task.get("desc") or "") + (f"\n{topics}" if topics else "")).strip()
            ok, result_url, error = await driver.publish_douyin_video(
                storage_state,
                self.allocator.allocate("douyin", "publish"),
                files,
                task.get("title") or "",
                body,
                visibility=task.get("visibility") or "public",
                allow_save=bool(task.get("allow_save", True)),
            )
            updates = {
                "status": STATUS_DONE if ok else STATUS_FAILED,
                "result_url": result_url,
                "error": error,
            }
            if ok:
                updates["published_at"] = _now_iso()
            return self.store.update(task["id"], updates)
        finally:
            self._busy = False
