"""console 任务实现：全部复用应用内调度器的 run_once 代码路径，跑完即退出。

约定：每个任务返回一个 dict，必须含 ``ok`` 布尔（决定进程退出码），其余字段
原样输出为 JSON 摘要，便于 cron / 监控系统解析。
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from flowpulse.config import get_settings
from flowpulse.runtime import Runtime, build_runtime


@dataclass(frozen=True)
class TaskSpec:
    name: str
    help: str
    run: Callable[[Runtime], Awaitable[dict]]


async def weread_sync(rt: Runtime) -> dict:
    """全量订阅增量同步一次（与内置调度循环同一代码路径，含状态记录与告警）。"""
    result = await rt.weread_scheduler.run_once()
    return {**result, "ok": result.get("error_count", 0) == 0}


async def weread_status(rt: Runtime) -> dict:
    """凭证与订阅健康检查：凭证缺失或任一订阅认证失败时 ok=False（纯离线，不请求微信读书）。"""
    credential = rt.weread_repository.get_credential()
    subs = rt.weread_service.list_subscriptions()
    auth_errors = [s for s in subs if s.last_sync_status == "auth_error"]
    return {
        "ok": bool(credential) and not auth_errors,
        "credential": {
            "configured": bool(credential),
            "valid": credential.valid if credential else None,
            "last_validated_at": credential.last_validated_at if credential else None,
        },
        "subscriptions": len(subs),
        "auth_error_subscriptions": [
            {"book_id": s.book_id, "name": s.name} for s in auth_errors
        ],
    }


async def weread_refresh_cookie(rt: Runtime) -> dict:
    """无头续期微信读书 Cookie 一次（需本机扫码浏览器的持久化 profile）。"""
    return await rt.weread_cookie_refresher.run_once()


async def xhs_check(rt: Runtime) -> dict:
    """小红书各平台登录态校验一次（掉线时按配置推 Webhook 告警）。"""
    results = await rt.xhs_credential_checker.run_once()
    ok = bool(results) and all(r.get("logged_in") is True for r in results.values())
    return {"ok": ok, "platforms": results}


async def xhs_monitor_scan(rt: Runtime) -> dict:
    """小红书作品监控：扫描全部到期目标一次（无到期目标为空跑）。"""
    result = await rt.xhs_monitor_scheduler.run_once()
    return {**result, "ok": result.get("errors", 0) == 0}


async def douyin_monitor_scan(rt: Runtime) -> dict:
    """抖音作品监控：扫描全部到期目标一次（浏览器拦截式，需已配置抖音账号）。"""
    result = await rt.douyin_monitor_scheduler.run_once()
    return {**result, "ok": result.get("errors", 0) == 0}


async def ks_monitor_scan(rt: Runtime) -> dict:
    """快手作品监控：扫描全部到期目标一次（浏览器拦截式，需已配置快手账号）。"""
    result = await rt.ks_monitor_scheduler.run_once()
    return {**result, "ok": result.get("errors", 0) == 0}


TASKS: dict[str, TaskSpec] = {
    spec.name: spec
    for spec in (
        TaskSpec("weread-sync", "微信读书：全量订阅增量同步一次", weread_sync),
        TaskSpec("weread-status", "微信读书：凭证与订阅健康检查（异常时退出码非 0）", weread_status),
        TaskSpec(
            "weread-refresh-cookie", "微信读书：无头 Cookie 续期一次（需本机浏览器 profile）", weread_refresh_cookie
        ),
        TaskSpec("xhs-check", "小红书：登录态校验一次", xhs_check),
        TaskSpec("xhs-monitor-scan", "小红书：作品监控到期目标扫描一次", xhs_monitor_scan),
        TaskSpec("douyin-monitor-scan", "抖音：作品监控到期目标扫描一次", douyin_monitor_scan),
        TaskSpec("ks-monitor-scan", "快手：作品监控到期目标扫描一次", ks_monitor_scan),
    )
}


def run_task(name: str) -> int:
    """执行单个任务并输出 JSON 摘要；返回进程退出码（0 成功 / 1 失败 / 2 未知任务）。"""
    spec = TASKS.get(name)
    if spec is None:
        print(f"未知任务：{name}（用 list 命令查看全部任务）", file=sys.stderr)
        return 2
    runtime = build_runtime(get_settings())
    try:
        result = asyncio.run(spec.run(runtime))
    except Exception as exc:  # noqa: BLE001 - CLI 顶层兜底，错误进摘要而非 traceback
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        asyncio.run(runtime.aclose())
    output = {"task": name, **result}
    print(json.dumps(output, ensure_ascii=False, default=str))
    return 0 if output.get("ok") else 1


def list_tasks() -> int:
    """列出全部可用任务。"""
    for spec in TASKS.values():
        print(f"{spec.name:<22} {spec.help}")
    return 0
