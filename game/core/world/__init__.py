"""世界地点查询功能。"""

from .contracts import LocationQuery, LocationView, WorldStatus
from .service import WorldService

__all__ = ["LocationQuery", "LocationView", "WorldService", "WorldStatus"]
