"""世界微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


class WorldDataError(ValueError):
    """世界 JSON 不能形成一致的地表事实。"""


@dataclass(frozen=True)
class SurfaceCoordinate:
    x: int
    y: int


LocationReference: TypeAlias = str | SurfaceCoordinate | tuple[int, int]


@dataclass(frozen=True)
class SurfacePoint:
    coordinate: SurfaceCoordinate
    altitude: int


@dataclass(frozen=True)
class SurfaceBounds:
    x_min: int
    x_max: int
    y_min: int
    y_max: int

    def contains(self, coordinate: SurfaceCoordinate) -> bool:
        return (
            self.x_min <= coordinate.x <= self.x_max
            and self.y_min <= coordinate.y <= self.y_max
        )


@dataclass(frozen=True)
class AltitudeRange:
    minimum: int
    maximum: int


@dataclass(frozen=True)
class RegionTerrainDefinition:
    name: str
    bounds: SurfaceBounds
    terrain: str


@dataclass(frozen=True)
class WorldDefinition:
    identity: str
    description: str
    birthplace: str
    bounds: SurfaceBounds
    altitude_range: AltitudeRange
    meters_per_grid: int
    road_types: tuple[str, ...]
    travel_rule: str


@dataclass(frozen=True)
class RegionDefinition:
    identity: str
    category: str
    bounds: SurfaceBounds
    altitude_range: AltitudeRange
    terrain_partitions: tuple[RegionTerrainDefinition, ...]
    description: str


@dataclass(frozen=True)
class LocationFeatureDefinition:
    name: str
    nonempty_fields: tuple[str, ...]
    positive_range_fields: tuple[str, ...]


@dataclass(frozen=True)
class LocationDefinition:
    identity: str
    region: str
    coordinate: SurfaceCoordinate
    altitude: int
    location_type: str
    terrain: str
    description: str
    available_features: tuple[str, ...]
    plant_pools: tuple[str, ...]
    mineral_pools: tuple[str, ...]
    companion_pools: tuple[str, ...]
    enemy_pools: tuple[str, ...]
    encounter_count: tuple[int, int]


@dataclass(frozen=True)
class RoadDefinition:
    road_type: str
    start: str
    destination: str
    coordinates: tuple[SurfaceCoordinate, ...]


@dataclass(frozen=True)
class WorldStatus:
    initialized: bool
    world_count: int
    region_count: int
    location_count: int
    road_count: int
    feature_count: int


__all__ = [
    "AltitudeRange",
    "LocationDefinition",
    "LocationFeatureDefinition",
    "LocationReference",
    "RegionDefinition",
    "RegionTerrainDefinition",
    "RoadDefinition",
    "SurfaceBounds",
    "SurfaceCoordinate",
    "SurfacePoint",
    "WorldDataError",
    "WorldDefinition",
    "WorldStatus",
]
