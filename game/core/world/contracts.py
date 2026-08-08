"""世界功能对外公开的数据契约。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorldStatus:
    initialized: bool
    location_count: int
    region_count: int
    road_count: int
    terrain_cell_count: int


@dataclass(frozen=True)
class LocationQuery:
    location_name: str = ""
    xy: tuple[int, int] | None = None


@dataclass(frozen=True)
class LocationView:
    location_key: str
    location_name: str
    xy: tuple[int, int]
    region: str
    terrain: str
    altitude: int
    available_functions: tuple[str, ...]
    plant_pool: tuple[str, ...]
    mineral_pool: tuple[str, ...]
    companion_pool: tuple[str, ...]
    enemy_pool: tuple[str, ...]
    enemy_count: tuple[int, ...]


@dataclass(frozen=True)
class MapCoordinateBand:
    y: int
    x_ranges: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class MapTerrainZone:
    name: str
    terrain: str
    bounds: tuple[int, int, int, int]
    label_xy: tuple[int, int]
    cell_count: int
    coordinate_bands: tuple[MapCoordinateBand, ...]


@dataclass(frozen=True)
class MapRegion:
    name: str
    category: str
    description: str
    bounds: tuple[int, int, int, int]
    label_xy: tuple[int, int]
    cell_count: int
    coordinate_bands: tuple[MapCoordinateBand, ...]
    terrain_zones: tuple[str, ...]


@dataclass(frozen=True)
class MapLocation:
    key: str
    name: str
    description: str
    xy: tuple[int, int]
    region: str
    terrain: str
    altitude: int
    available_functions: tuple[str, ...]


@dataclass(frozen=True)
class MapRoad:
    road_type: str
    start_key: str
    end_key: str
    start: str
    end: str
    coordinates: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class WorldMapView:
    schema: str
    version: int
    name: str
    description: str
    birthplace_key: str
    birthplace: str
    bounds: tuple[int, int, int, int]
    cell_size_meters: int
    altitude_range: tuple[int, int]
    surface: tuple[tuple[int, ...], ...]
    regions: tuple[MapRegion, ...]
    terrain_zones: tuple[MapTerrainZone, ...]
    locations: tuple[MapLocation, ...]
    roads: tuple[MapRoad, ...]


__all__ = [
    "LocationQuery",
    "LocationView",
    "MapCoordinateBand",
    "MapLocation",
    "MapRegion",
    "MapRoad",
    "MapTerrainZone",
    "WorldMapView",
    "WorldStatus",
]
