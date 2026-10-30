"""浏览器引擎封装：patchright 优先、官方 playwright 回退（D1 决策），统一 async 接口。

抖音读取/登录均走系统 Chrome（channel="chrome"，免下载 Chromium）；
未安装任一引擎时上层会得到明确的 ImportError 提示。
"""

from __future__ import annotations

from typing import Any

DOUYIN_DOMAIN = ".douyin.com"


def load_browser_module() -> tuple[Any, str]:
    """返回 (playwright 模块, 引擎名)。patchright 缺失时回退官方 playwright。"""
    try:
        from patchright import async_api as patchright_api

        return patchright_api, "patchright"
    except ImportError:
        pass
    try:
        from playwright import async_api as playwright_api

        return playwright_api, "playwright"
    except ImportError as exc:
        raise ImportError(
            "未安装浏览器引擎：pip install -e \".[browser]\"（patchright）或 pip install playwright"
        ) from exc


def browser_engine_name() -> str:
    try:
        return load_browser_module()[1]
    except ImportError:
        return "none"


class ManagedContext:
    """context + playwright 实例的包装：close() 同时收掉两者，属性访问透传 context。"""

    def __init__(self, context, playwright_instance) -> None:
        self._context = context
        self._playwright = playwright_instance

    def __getattr__(self, name):
        return getattr(self._context, name)

    @property
    def pages(self):
        return self._context.pages

    async def new_page(self):
        return await self._context.new_page()

    async def cookies(self, urls=None):
        return await self._context.cookies(urls)

    async def close(self) -> None:
        try:
            await self._context.close()
        finally:
            try:
                await self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass


async def launch_persistent_context(
    profile_dir,
    headless: bool = True,
    storage_state: dict | None = None,
) -> ManagedContext:
    """以持久化 Profile 启动系统 Chrome；storage_state 可选注入登录态。"""
    api, _ = load_browser_module()
    playwright_instance = await api.async_playwright().start()
    kwargs: dict[str, Any] = {
        "channel": "chrome",
        "headless": headless,
        "viewport": None,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if storage_state is not None:
        kwargs["storage_state"] = storage_state
    try:
        context = await playwright_instance.chromium.launch_persistent_context(
            str(profile_dir), **kwargs
        )
    except Exception:
        await playwright_instance.stop()
        raise
    return ManagedContext(context, playwright_instance)


def cookie_string_to_parts(cookie: str) -> list[dict]:
    """"k1=v1; k2=v2" → playwright cookies 列表（挂 .douyin.com）。"""
    cookies = []
    for chunk in (cookie or "").split(";"):
        if "=" not in chunk:
            continue
        name, _, value = chunk.strip().partition("=")
        if not name:
            continue
        cookies.append(
            {"name": name, "value": value, "domain": DOUYIN_DOMAIN, "path": "/"}
        )
    return cookies


def storage_state_from_cookie(cookie: str) -> dict | None:
    parts = cookie_string_to_parts(cookie)
    if not parts:
        return None
    return {"cookies": parts, "origins": []}


def cookie_from_context_cookies(cookies: list[dict]) -> str:
    """context.cookies() → "k1=v1; k2=v2"（只保留抖音域）。"""
    pairs = []
    for item in cookies or []:
        if "douyin.com" not in (item.get("domain") or ""):
            continue
        pairs.append(f"{item['name']}={item['value']}")
    return "; ".join(pairs)


def has_login_cookie(cookie: str) -> bool:
    return "sessionid=" in (cookie or "") and "ttwid=" in (cookie or "")
