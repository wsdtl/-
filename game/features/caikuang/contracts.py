"""采矿玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.gathering import (
    GatheredItem,
    GatheringProgress,
    GatheringSettlement,
    GatheringStarted,
    GatheringUserSummary,
)


class OreGatheringFeatureError(RuntimeError):
    """采矿玩法无法完成请求。"""


@dataclass(frozen=True)
class OreGatheringAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class OreGatheringCopy:
    text: Mapping[str, Mapping[str, str]]


__all__ = [
    "GatheredItem",
    "GatheringProgress",
    "GatheringSettlement",
    "GatheringStarted",
    "GatheringUserSummary",
    "OreGatheringAction",
    "OreGatheringCopy",
    "OreGatheringFeatureError",
]
