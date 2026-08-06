"""世界功能对外公开的数据契约。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorldStatus:
    initialized: bool
    location_count: int
    region_count: int
    terrain_cell_count: int


@dataclass(frozen=True)
class LocationQuery:
    name: str = ""
    coordinate: tuple[int, int] | None = None


@dataclass(frozen=True)
class LocationView:
    name: str
    coordinate: tuple[int, int]
    location_type: str
    region: str
    terrain: str
    altitude: int
    available_functions: tuple[str, ...]
    plant_pool: tuple[str, ...]
    mineral_pool: tuple[str, ...]
    companion_pool: tuple[str, ...]
    enemy_pool: tuple[str, ...]
    enemy_count: tuple[int, ...]


__all__ = ["LocationQuery", "LocationView", "WorldStatus"]
