"""小红书作品监控（P1）：监控目标管理 + 增量扫描调度 + 作品记录 + 新作品通知。

依赖 integration.XhsService 的 user_notes / search 能力；存储与调度模式对齐 weread。
"""

from flowpulse.modules.xhs.monitoring.routes import (
    get_monitor_scheduler,
    get_monitor_service,
    router,
)
from flowpulse.modules.xhs.monitoring.scheduler import XhsMonitorScheduler
from flowpulse.modules.xhs.monitoring.service import XhsMonitorService
from flowpulse.modules.xhs.monitoring.store import XhsMonitorRepository

__all__ = [
    "XhsMonitorRepository",
    "XhsMonitorScheduler",
    "XhsMonitorService",
    "get_monitor_scheduler",
    "get_monitor_service",
    "router",
]
