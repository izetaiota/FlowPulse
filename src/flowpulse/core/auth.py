"""Web 登录鉴权：单账号（用户名/密码），无菜单权限体系。

设计：
  - 账号持久化：DATABASE_URL 模式落 fp_users 表（单行），文件模式落 data/auth/users.json；
    密码只存 PBKDF2 哈希，永不存明文
  - 首次启动（存储为空）时用环境变量 ADMIN_USERNAME/ADMIN_PASSWORD 种子写入，
    之后以存储为准——改环境变量不再覆盖，改密走 /api/auth/password
  - 未配置 ADMIN_PASSWORD 且存储无账号时鉴权关闭（本地零配置直通）
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
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.core.storage import atomic_write_json, read_json
from flowpulse.db.models import UserRow

TOKEN_TTL_SECONDS = 7 * 24 * 3600
PBKDF2_ITERATIONS = 200_000

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6, max_length=128)


# --- 密码哈希（标准库实现，避免引入额外依赖） ------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, expected = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


# --- 账号存储（双模式，与菜单存储同一套路） --------------------------------


class AuthUserStore:
    """登录账号存储：DATABASE_URL 模式走 fp_users 表（单行），否则 data/auth/users.json。"""

    def __init__(self, sessionmaker_: sessionmaker[Session] | None, json_path: Path):
        self._sessionmaker = sessionmaker_
        self._json_path = json_path
        self._json_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict | None:
        """返回 {username, password_hash}；无账号返回 None。"""
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                row = session.get(UserRow, 1)
                if row is None:
                    return None
                return {"username": row.username, "password_hash": row.password_hash}
        data = read_json(self._json_path, {})
        if not data.get("username"):
            return None
        return {"username": data["username"], "password_hash": data.get("password_hash", "")}

    def save(self, username: str, password_hash: str) -> None:
        if self._sessionmaker is not None:
            with self._sessionmaker() as session:
                session.execute(sa_delete(UserRow))
                session.add(UserRow(username=username, password_hash=password_hash))
                session.commit()
        else:
            atomic_write_json(
                self._json_path, {"username": username, "password_hash": password_hash}
            )


# --- 鉴权状态与 Token ------------------------------------------------------


_state: dict = {"username": "admin", "password": "", "secret": b"", "store": None}


def init_auth(
    username: str,
    password: str,
    data_dir: Path,
    store: AuthUserStore | None = None,
) -> None:
    _state["username"] = username or "admin"
    _state["password"] = password or ""
    _state["store"] = store
    # 首启种子：存储为空且配置了密码时写入；此后以存储为准（环境变量不再覆盖）
    if store is not None and password and store.load() is None:
        store.save(_state["username"], hash_password(password))
    secret_path = Path(data_dir) / ".auth_secret"
    try:
        secret = secret_path.read_text(encoding="utf-8").strip()
    except OSError:
        secret = secrets.token_hex(32)
        secret_path.write_text(secret, encoding="utf-8")
    _state["secret"] = secret.encode()


def _load_user() -> dict | None:
    store = _state.get("store")
    return store.load() if store is not None else None


def auth_enabled() -> bool:
    if _state.get("store") is not None:
        return _load_user() is not None
    return bool(_state["password"])


def _verify_credentials(username: str, password: str) -> bool:
    user = _load_user()
    if _state.get("store") is not None:
        if user is None:
            return False
        return hmac.compare_digest(username, user["username"]) and verify_password(
            password, user["password_hash"]
        )
    # 未接存储（如单元测试直调）：退回环境变量明文比较
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


# --- API -------------------------------------------------------------------


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
    """前端启动时探测：鉴权是否启用、当前是否已登录。

    鉴权关闭时也返回部署配置的真实账号名（ADMIN_USERNAME），前端顶栏按真实账号展示。
    """
    if not auth_enabled():
        user = _load_user()
        return {"enabled": False, "username": (user or {}).get("username") or _state["username"]}
    token = request.headers.get("authorization", "")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    username = verify_token(token) if token else None
    if username is None:
        return {"enabled": True, "username": ""}
    # 以存储中的账号名为准（token 签发后账号名不会变，此处仅兜底展示）
    user = _load_user()
    return {"enabled": True, "username": (user or {}).get("username") or username}


@router.post("/api/auth/password", dependencies=[Depends(require_auth)])
def change_password(request: ChangePasswordRequest) -> dict:
    """修改登录密码（账号名不变；旧密码校验通过后更新存储中的哈希）。"""
    if not auth_enabled():
        raise HTTPException(status_code=409, detail="鉴权未启用，无需修改密码")
    store = _state.get("store")
    if store is None:
        raise HTTPException(status_code=501, detail="当前运行模式不支持在线改密")
    user = _load_user()
    if user is None or not verify_password(request.old_password, user["password_hash"]):
        raise HTTPException(status_code=403, detail="旧密码不正确")
    store.save(user["username"], hash_password(request.new_password))
    return {"message": "密码已更新"}
