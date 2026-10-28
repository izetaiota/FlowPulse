"""前端静态资源伺服：单容器部署时由 FastAPI 直接输出工作台页面（SPA）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

# 这些前缀保留给 API 与健康检查：未命中时保持 404，不回退到前端页面
_RESERVED_PREFIXES = ("api/", "health/")


class SPAStaticFiles(StaticFiles):
    """未命中的非 API 路径回退 index.html，交给前端路由（如 /dashboard）。"""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # Windows 下路径分隔符会被规范成反斜杠，统一成 / 再比较前缀
            normalized = path.replace("\\", "/").lstrip("/")
            if exc.status_code == 404 and not normalized.startswith(_RESERVED_PREFIXES):
                return await super().get_response("index.html", scope)
            raise


def mount_static_site(app: FastAPI, directory: str | Path) -> bool:
    """目录含 index.html 时挂载到根路径；必须在所有 API 路由注册之后调用。"""
    root = Path(directory)
    if not (root / "index.html").is_file():
        return False
    app.mount("/", SPAStaticFiles(directory=root, html=True), name="static_site")
    return True
