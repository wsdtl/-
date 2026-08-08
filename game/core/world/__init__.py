"""世界地点与只读地图功能。"""

from .contracts import (
    JourneyMetrics,
    JourneyPassageSegment,
    JourneyPlan,
    JourneyQuery,
    LocationQuery,
    LocationView,
    MapCoordinateBand,
    MapLocation,
    MapRegion,
    MapRoad,
    MapTerrainZone,
    WorldMapView,
    WorldStatus,
)
from .service import WorldService

__all__ = [
    "JourneyMetrics",
    "JourneyPassageSegment",
    "JourneyPlan",
    "JourneyQuery",
    "LocationQuery",
    "LocationView",
    "MapCoordinateBand",
    "MapLocation",
    "MapRegion",
    "MapRoad",
    "MapTerrainZone",
    "WorldMapView",
    "WorldService",
    "WorldStatus",
]
