"""世界、地势、地点与道路公共微服务。"""

from .contracts import AltitudeRange as AltitudeRange
from .contracts import LocationDefinition as LocationDefinition
from .contracts import LocationFeatureDefinition as LocationFeatureDefinition
from .contracts import LocationReference as LocationReference
from .contracts import RegionDefinition as RegionDefinition
from .contracts import RoadDefinition as RoadDefinition
from .contracts import SurfaceBounds as SurfaceBounds
from .contracts import SurfaceCoordinate as SurfaceCoordinate
from .contracts import SurfacePoint as SurfacePoint
from .contracts import WorldDataError as WorldDataError
from .contracts import WorldDefinition as WorldDefinition
from .contracts import WorldStatus as WorldStatus
from .service import WorldService as WorldService

__all__ = [
    "AltitudeRange",
    "LocationDefinition",
    "LocationFeatureDefinition",
    "LocationReference",
    "RegionDefinition",
    "RoadDefinition",
    "SurfaceBounds",
    "SurfaceCoordinate",
    "SurfacePoint",
    "WorldDataError",
    "WorldDefinition",
    "WorldService",
    "WorldStatus",
]
