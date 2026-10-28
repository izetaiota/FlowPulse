"""Web 登录鉴权：单账号（用户名/密码），无菜单权限体系。

设计：
  - 未配置 ADMIN_PASSWORD 时鉴权关闭（本地零配置直通，行为与从前一致）
  - 配置后：除 /api/auth/*、/health* 外的全部 API 需要 Bearer Token
  - Token 为 HMAC 签名的时间戳凭证（默认 7 天），服务重启不失效；
    签名密钥自动生成于 data/.auth_secret
  - 兼容 `?token=` 查询参数（RSS 阅读器等无法带 Header 的客户端）
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

TOKEN_TTL_SECONDS = 7 * 24 * 3600

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


_state: dict = {"username": "admin", "password": "", "secret": b""}


def init_auth(username: str, password: str, data_dir: Path) -> None:
    _state["username"] = username or "admin"
    _state["password"] = password or ""
    secret_path = Path(data_dir) / ".auth_secret"
    try:
        secret = secret_path.read_text(encoding="utf-8").strip()
    except OSError:
        secret = secrets.token_hex(32)
        secret_path.write_text(secret, encoding="utf-8")
    _state["secret"] = secret.encode()


def auth_enabled() -> bool:
    return bool(_state["password"])


def _verify_credentials(username: str, password: str) -> bool:
    return hmac.compare_digest(username, _state["username"]) and hmac.compare_digest(
        password, _state["password"]
    )


def _sign(payload: str) -> str:
    return hmac.new(_state["secret"], payload.encode(), hashlib.sha256).hexdigest()


def create_token(username: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> tuple[str, int]:
    expires_at = int(time.time()) + ttl_seconds
    payload = f"{username}.{expires_at}"
    return f"{payload}.{_sign(payload)}", expires_at


def verify_token(token: str) -> str | None:
    """校验 token，返回用户名；无效/过期返回 None。"""
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    username, expires_at, signature = parts
    if not hmac.compare_digest(_sign(f"{username}.{expires_at}"), signature):
        return None
    try:
        if int(expires_at) < time.time():
            return None
    except ValueError:
        return None
    return username


def require_auth(request: Request) -> None:
    """FastAPI 依赖：鉴权未启用时直通；否则校验 Header 或查询参数里的 token。"""
    if not auth_enabled():
        return
    if request.url.path.startswith("/health"):
        return
    token = None
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    token = token or request.query_params.get("token", "")
    username = verify_token(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")


@router.post("/api/auth/login")
def login(request: LoginRequest) -> dict:
    if not auth_enabled():
        return {"token": "", "username": request.username, "expires_at": 0,
                "message": "鉴权未启用，无需登录"}
    if not _verify_credentials(request.username, request.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token, expires_at = create_token(request.username)
    return {"token": token, "username": request.username, "expires_at": expires_at}


@router.get("/api/auth/session")
def session(request: Request) -> dict:
    """前端启动时探测：鉴权是否启用、当前是否已登录。"""
    if not auth_enabled():
        return {"enabled": False, "username": ""}
    token = request.headers.get("authorization", "")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    username = verify_token(token) if token else None
    return {"enabled": True, "username": username or ""}
