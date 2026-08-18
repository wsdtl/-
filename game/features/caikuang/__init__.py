"""采矿玩法微服务。"""

from .contracts import (
    GatheredItem,
    GatheringProgress,
    GatheringSettlement,
    GatheringStarted,
    GatheringUserSummary,
    OreGatheringAction,
    OreGatheringCopy,
    OreGatheringFeatureError,
)
from .service import OreGatheringFeature

__all__ = [
    "GatheredItem",
    "GatheringProgress",
    "GatheringSettlement",
    "GatheringStarted",
    "GatheringUserSummary",
    "OreGatheringAction",
    "OreGatheringCopy",
    "OreGatheringFeature",
    "OreGatheringFeatureError",
]
