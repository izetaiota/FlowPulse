"""浏览器会话层骨架（P0.5）：Profile 分配 + 常驻上下文 LRU + 登录驱动状态机接口。

本模块在 P0 阶段不启动任何浏览器（patchright 为可选依赖，仅在启用浏览器登录时安装），
只提供与浏览器无关、可单测的纯逻辑；P3 抖音/P5 平台接入时在此之上实现具体驱动。

设计参照 creatorhub 的 BrowserManager 思路（每账号持久 Profile、上下文 LRU 回收、
登录驱动 start→poll→verify），以 FlowPulse 自研实现落地。
"""

from __future__ import annotations

import re
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def slugify(text: str, fallback: str = "acc") -> str:
    slug = _SLUG_RE.sub("-", (text or "").strip()).strip("-")
    return slug[:32] or fallback


class ProfileAllocator:
    """每账号一个持久 user-data-dir，uuid 命名永不复用（防删号后目录被新账号顶替串 cookie）。"""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def allocate(self, platform: str, account_key: str) -> Path:
        name = f"{slugify(platform)}-{slugify(account_key)}-{uuid.uuid4().hex[:8]}"
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path


class ContextRegistry:
    """常驻浏览器上下文的 LRU 登记：touch 更新最近使用，超量的按最久未用驱逐。"""

    def __init__(self, max_live_contexts: int = 4):
        self._max = max(1, int(max_live_contexts))
        # key: (platform, account_key)；value 由驱动层自定义（P3 起为 context 句柄）
        self._entries: OrderedDict[tuple[str, str], object] = OrderedDict()

    def put(self, platform: str, account_key: str, handle: object) -> list[tuple[str, str]]:
        """登记/刷新上下文，返回被驱逐的键列表（驱动层负责异步关闭对应上下文）。"""
        key = (platform, account_key)
        self._entries[key] = handle
        self._entries.move_to_end(key)
        evicted: list[tuple[str, str]] = []
        while len(self._entries) > self._max:
            evicted.append(self._entries.popitem(last=False)[0])
        return evicted

    def get(self, platform: str, account_key: str) -> object | None:
        return self._entries.get((platform, account_key))

    def touch(self, platform: str, account_key: str) -> None:
        self._entries.move_to_end((platform, account_key))

    def drop(self, platform: str, account_key: str) -> object | None:
        return self._entries.pop((platform, account_key), None)

    def keys(self) -> list[tuple[str, str]]:
        return list(self._entries.keys())


class LoginDriverState(StrEnum):
    """登录驱动状态机（与 xhs LoginDriver 的 start→poll→verify 三段式一致）。"""

    PENDING = "pending"        # 已发起（二维码已生成 / 短信已发送）
    WAITING = "waiting"        # 等待用户动作（扫码 / 输入验证码）
    CONFIRMING = "confirming"  # 平台侧确认中
    LOGGED_IN = "logged_in"    # 登录成功
    EXPIRED = "expired"        # 二维码/验证码过期
    FAILED = "failed"          # 失败（可重新发起）
    CANCELLED = "cancelled"    # 用户取消


@dataclass
class LoginSessionState:
    """一次交互式登录的会话状态（浏览器层各平台驱动的统一载体）。"""

    platform: str
    account_key: str
    state: LoginDriverState = LoginDriverState.PENDING
    message: str = ""
    # 二维码图片 base64 / 短信手机号掩码等驱动专属载荷
    payload: dict = field(default_factory=dict)

    def transition(self, next_state: LoginDriverState, message: str = "") -> None:
        terminal = {LoginDriverState.LOGGED_IN, LoginDriverState.FAILED, LoginDriverState.CANCELLED}
        if self.state in terminal:
            raise ValueError(f"登录会话已结束（{self.state}），不能转为 {next_state}")
        self.state = next_state
        self.message = message
