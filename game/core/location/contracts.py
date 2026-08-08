"""玩家地表位置核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class LocationError(RuntimeError):
    """玩家位置无法完成请求。"""


class LocationMissingError(LocationError):
    """玩家尚无地表位置。"""


class LocationConflictError(LocationError):
    """玩家位置已被另一项业务改变。"""


@dataclass(frozen=True)
class LocationServiceStatus:
    initialized: bool
    player_count: int
    nearby_radius_meters: int
    nearby_page_size: int
    nearby_visible_limit: int


@dataclass(frozen=True)
class PlayerLocation:
    user_id: str
    xy: tuple[int, int]
    version: int
    updated_at: str


@dataclass(frozen=True)
class NearbyPlayerLocation:
    user_id: str
    xy: tuple[int, int]
    distance_squared_meters: int


@dataclass(frozen=True)
class NearbyPlayerCandidates:
    origin: PlayerLocation
    values: tuple[NearbyPlayerLocation, ...]
    candidate_limit_reached: bool
    page_size: int
    visible_limit: int


@dataclass(frozen=True)
class LocationMoveCommand:
    user_id: str
    request_id: str
    expected_origin_xy: tuple[int, int]
    destination_xy: tuple[int, int]


@dataclass(frozen=True)
class LocationMoveResult:
    user_id: str
    origin_xy: tuple[int, int]
    destination_xy: tuple[int, int]
    changed: bool
    replayed: bool


__all__ = [
    "LocationConflictError",
    "LocationError",
    "LocationMissingError",
    "LocationMoveCommand",
    "LocationMoveResult",
    "LocationServiceStatus",
    "NearbyPlayerCandidates",
    "NearbyPlayerLocation",
    "PlayerLocation",
]
