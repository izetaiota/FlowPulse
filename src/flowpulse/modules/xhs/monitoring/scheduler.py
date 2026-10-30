"""小红书作品监控调度器：通用 MonitorScheduler 的平台包装。"""

from __future__ import annotations

from flowpulse.modules.platforms import MonitorScheduler
from flowpulse.modules.xhs.monitoring.service import XhsMonitorService
from flowpulse.modules.xhs.monitoring.store import XhsMonitorRepository


class XhsMonitorScheduler(MonitorScheduler):
    """到期轮询 + 串行扫描（逻辑继承 monitor_core，签名保持兼容）。"""

    def __init__(
        self,
        service: XhsMonitorService,
        repository: XhsMonitorRepository,
        tick_seconds: int = 60,
        enabled: bool = True,
    ) -> None:
        super().__init__(service, repository, tick_seconds=tick_seconds, enabled=enabled)
