"""托管玩法微服务。"""

from .contracts import HostingCopy, HostingFeatureError, HostingResult
from .service import HostingFeature

__all__ = ["HostingCopy", "HostingFeature", "HostingFeatureError", "HostingResult"]
