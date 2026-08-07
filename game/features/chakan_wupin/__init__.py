"""查看物品玩法微服务。"""

from .contracts import ItemInspectionResult
from .service import ItemInspectionFeature

__all__ = ["ItemInspectionFeature", "ItemInspectionResult"]
