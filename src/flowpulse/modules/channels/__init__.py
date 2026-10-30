"""视频号平台模块（P5-T5.2）：extract / browser / service。"""

from flowpulse.modules.channels.service import (
    ChannelsService,
    ChannelsStore,
    get_channels_service,
    router,
)

__all__ = ["ChannelsService", "ChannelsStore", "get_channels_service", "router"]
