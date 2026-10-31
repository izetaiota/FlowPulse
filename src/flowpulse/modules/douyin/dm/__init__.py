"""抖音私信模块（T4.4）：protocol / ws / service / routes。"""

from flowpulse.modules.douyin.dm.routes import get_douyin_dm_service, router
from flowpulse.modules.douyin.dm.service import DouyinDmService

__all__ = ["DouyinDmService", "get_douyin_dm_service", "router"]
