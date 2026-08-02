"""正式 JSON 数据核心微服务。"""

from .contracts import JsonDataError as JsonDataError
from .contracts import JsonDataStatus as JsonDataStatus
from .service import JsonDataService as JsonDataService

__all__ = ["JsonDataError", "JsonDataService", "JsonDataStatus"]
