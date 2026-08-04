"""行程微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.world import LocationReference, SurfaceCoordinate, SurfacePoint


class TravelError(ValueError):
    """行程请求无效或地表无法形成路线。"""


@dataclass(frozen=True)
class TravelEndpoint:
    """行路端点；动态业务只需提供展示名和二维地表坐标。"""

    label: str
    coordinate: SurfaceCoordinate


@dataclass(frozen=True)
class TravelRequest:
    start: LocationReference | TravelEndpoint
    destination: LocationReference | TravelEndpoint


@dataclass(frozen=True)
class TravelMetrics:
    horizontal_distance: int
    road_segments: int
    terrain_segments: int
    minimum_altitude: int
    maximum_altitude: int
    total_ascent: int
    total_descent: int
    maximum_step_up: int
    maximum_step_down: int
    maximum_uphill_per_mille: float
    maximum_downhill_per_mille: float
    adjusted_distance: int


@dataclass(frozen=True)
class TravelPlan:
    start: str
    destination: str
    destination_region: str
    via_locations: tuple[str, ...]
    road_types: tuple[str, ...]
    terrain_types: tuple[str, ...]
    terrain_turning_location: str
    terrain_turning_coordinate: SurfaceCoordinate | None
    points: tuple[SurfacePoint, ...]
    metrics: TravelMetrics
    narrative: str


@dataclass(frozen=True)
class TravelStatus:
    initialized: bool
    metric_count: int
    road_count: int


@dataclass(frozen=True)
class TravelRealmEffects:
    destination_reachability: bool
    road_availability: bool
    travel_method: bool
    travel_speed: bool
    display_wording: bool


__all__ = [
    "TravelEndpoint",
    "TravelError",
    "TravelMetrics",
    "TravelPlan",
    "TravelRealmEffects",
    "TravelRequest",
    "TravelStatus",
]
