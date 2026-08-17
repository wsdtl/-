"""玩家地表位置核心微服务。"""

from .contracts import (
    GroupLocationMoveCommand,
    GroupLocationMoveResult,
    LocationConflictError,
    LocationError,
    LocationMissingError,
    LocationMoveCommand,
    LocationMoveResult,
    LocationServiceStatus,
    NearbyPlayerCandidates,
    NearbyPlayerLocation,
    PlayerLocation,
)
from .service import LocationService

__all__ = [
    "GroupLocationMoveCommand",
    "GroupLocationMoveResult",
    "LocationConflictError",
    "LocationError",
    "LocationMissingError",
    "LocationMoveCommand",
    "LocationMoveResult",
    "LocationService",
    "LocationServiceStatus",
    "NearbyPlayerCandidates",
    "NearbyPlayerLocation",
    "PlayerLocation",
]
