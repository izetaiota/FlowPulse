"""小红书私信模块出口（T4.1/T4.2）。"""

from flowpulse.modules.xhs.dm.routes import get_dm_rule_store, get_dm_service, router
from flowpulse.modules.xhs.dm.rules import DmRuleStore
from flowpulse.modules.xhs.dm.service import XhsDmService

__all__ = ["DmRuleStore", "XhsDmService", "get_dm_rule_store", "get_dm_service", "router"]
