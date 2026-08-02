"""行程微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.world import LocationReference, SurfacePoint


class TravelError(ValueError):
    """行程请求无效或正式路网无法形成路线。"""


@dataclass(frozen=True)
class TravelRequest:
    start: LocationReference
    destination: LocationReference


@dataclass(frozen=True)
class TravelMetrics:
    horizontal_distance: int
    road_segments: int
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
    terrain_turning_location: str
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
    "TravelError",
    "TravelMetrics",
    "TravelPlan",
    "TravelRealmEffects",
    "TravelRequest",
    "TravelStatus",
]
