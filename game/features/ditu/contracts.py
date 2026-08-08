"""公开地图展示玩法的公共结果。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorldMapOverview:
    name: str
    description: str
    width: int
    height: int
    region_count: int
    location_count: int
    road_count: int


__all__ = ["WorldMapOverview"]
