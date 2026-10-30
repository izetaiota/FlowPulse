"""写操作风控闸（T4.3，思想参照 creatorhub risk.py）：配额 / 失败冷却阶梯 / 安静时段。

单一实例内生效；状态落 data/risk/state.json（文件存储，PG 模式同样适用——
风控计数是短生命周期运行态，不入业务库）。首个接入方：抖音发布队列；
后续评论/关注/私信等写操作照此调用 preflight → record_success/record_failure。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from flowpulse.core.storage import atomic_write_json, read_json

# 失败冷却阶梯（秒）：连续失败第 1/2/3/4+ 次
COOLDOWN_LADDER = (1800, 7200, 21600, 86400)


def _now() -> int:
    return int(time.time())


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_hhmm(text: str) -> tuple[int, int] | None:
    try:
        hours, minutes = text.strip().split(":")
        return int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError):
        return None


class RiskGate:
    def __init__(
        self,
        state_path: Path,
        enabled: bool = True,
        hourly_limit: int = 10,
        daily_limit: int = 50,
        quiet_hours: str = "23:00-07:00",
    ):
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self.hourly_limit = max(0, int(hourly_limit))
        self.daily_limit = max(0, int(daily_limit))
        # 安静时段（本地时钟，如 "23:00-07:00" 跨午夜；空 = 关闭）
        self.quiet_start = self.quiet_end = None
        if "-" in (quiet_hours or ""):
            start, end = quiet_hours.split("-", 1)
            self.quiet_start = _parse_hhmm(start)
            self.quiet_end = _parse_hhmm(end)

    # ---- 状态 ----

    def _load(self) -> dict:
        return read_json(self.state_path, {"accounts": {}})

    def _save(self, state: dict) -> None:
        atomic_write_json(self.state_path, state)

    def _account(self, state: dict, key: str) -> dict:
        return state["accounts"].setdefault(
            key,
            {"hour_window": 0, "hour_count": 0, "day_date": "", "day_count": 0,
             "consecutive_failures": 0, "paused_until": 0},
        )

    # ---- 查询 ----

    def _in_quiet_hours(self, now: datetime | None = None) -> bool:
        if self.quiet_start is None or self.quiet_end is None:
            return False
        current = now or datetime.now()
        minutes = current.hour * 60 + current.minute
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= minutes < self.quiet_end
        return minutes >= self.quiet_start or minutes < self.quiet_end  # 跨午夜

    def preflight(self, platform: str, account_key: str) -> tuple[bool, str]:
        """写操作前检查；返回 (放行, 原因)。不放行时不消耗配额。"""
        if not self.enabled:
            return True, ""
        key = f"{platform}:{account_key}"
        state = self._load()
        account = self._account(state, key)
        now = _now()
        if account["paused_until"] > now:
            remaining = (account["paused_until"] - now) // 60 + 1
            return False, f"风控冷却中（连续失败 {account['consecutive_failures']} 次），约 {remaining} 分钟后恢复"
        if self._in_quiet_hours():
            return False, "安静时段（夜间），写操作暂停"
        # 小时窗口滚动
        if now - account["hour_window"] >= 3600:
            account["hour_window"] = now
            account["hour_count"] = 0
        if self.hourly_limit and account["hour_count"] >= self.hourly_limit:
            return False, f"已达小时配额（{self.hourly_limit} 次/时）"
        today = _today()
        if account["day_date"] != today:
            account["day_date"] = today
            account["day_count"] = 0
        if self.daily_limit and account["day_count"] >= self.daily_limit:
            return False, f"已达日配额（{self.daily_limit} 次/天）"
        self._save(state)
        return True, ""

    # ---- 记录 ----

    def record_success(self, platform: str, account_key: str) -> None:
        if not self.enabled:
            return
        key = f"{platform}:{account_key}"
        state = self._load()
        account = self._account(state, key)
        now = _now()
        if now - account["hour_window"] >= 3600:
            account["hour_window"] = now
            account["hour_count"] = 0
        account["hour_count"] += 1
        today = _today()
        if account["day_date"] != today:
            account["day_date"] = today
            account["day_count"] = 0
        account["day_count"] += 1
        account["consecutive_failures"] = 0
        self._save(state)

    def record_failure(self, platform: str, account_key: str) -> int:
        """失败一次：连续失败按阶梯冷却，返回本次冷却秒数。"""
        if not self.enabled:
            return 0
        key = f"{platform}:{account_key}"
        state = self._load()
        account = self._account(state, key)
        account["consecutive_failures"] += 1
        index = min(account["consecutive_failures"], len(COOLDOWN_LADDER)) - 1
        cooldown = COOLDOWN_LADDER[index]
        account["paused_until"] = _now() + cooldown
        self._save(state)
        return cooldown

    def clear(self, platform: str, account_key: str) -> None:
        state = self._load()
        state["accounts"].pop(f"{platform}:{account_key}", None)
        self._save(state)

    def status(self, platform: str, account_key: str) -> dict:
        state = self._load()
        account = state["accounts"].get(f"{platform}:{account_key}")
        if not account:
            return {"tracked": False}
        return {
            "tracked": True,
            "hour_count": account["hour_count"],
            "day_count": account["day_count"],
            "consecutive_failures": account["consecutive_failures"],
            "paused_until": account["paused_until"],
            "paused": account["paused_until"] > _now(),
        }
