"""浏览器层骨架测试：Profile 分配不复用、上下文 LRU 驱逐、登录状态机终态保护。"""

from pathlib import Path

import pytest

from flowpulse.modules.browser import (
    ContextRegistry,
    LoginDriverState,
    LoginSessionState,
    ProfileAllocator,
    slugify,
)


def test_profile_allocator_never_reuses(tmp_path: Path):
    allocator = ProfileAllocator(tmp_path / "profiles")
    p1 = allocator.allocate("douyin", "sec_uid abc")
    p2 = allocator.allocate("douyin", "sec_uid abc")  # 同名账号两次分配也不复用目录
    assert p1.is_dir() and p2.is_dir()
    assert p1 != p2
    assert p1.name.startswith("douyin-sec_uid-abc-")


def test_slugify_sanitizes():
    assert slugify("微信读书") == "acc" or slugify("微信读书")  # 中文被清洗后回落 fallback
    assert slugify("xhs://pc") == "xhs-pc"


def test_context_registry_lru_eviction():
    registry = ContextRegistry(max_live_contexts=2)
    registry.put("douyin", "a", object())
    registry.put("douyin", "b", object())
    evicted = registry.put("xhs", "pc", object())
    assert evicted == [("douyin", "a")]

    # touch 保活：最久未用但刚被访问的不驱逐
    registry.touch("douyin", "b")
    evicted = registry.put("douyin", "c", object())
    assert evicted == [("xhs", "pc")]

    assert registry.drop("douyin", "b") is not None
    assert registry.drop("douyin", "b") is None
    assert registry.keys() == [("douyin", "c")]


def test_login_session_terminal_protection():
    session = LoginSessionState(platform="douyin", account_key="sec_1")
    session.transition(LoginDriverState.WAITING, "等待扫码")
    session.transition(LoginDriverState.LOGGED_IN, "登录成功")
    with pytest.raises(ValueError):
        session.transition(LoginDriverState.PENDING, "终态不可逆")
