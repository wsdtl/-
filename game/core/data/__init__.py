"""正式 JSON 数据核心微服务。"""

from .contracts import JsonDataError as JsonDataError
from .contracts import JsonDataStatus as JsonDataStatus
from .contracts import JsonEntity as JsonEntity
from .contracts import JsonValue as JsonValue
from .service import JsonDataService as JsonDataService
from .service import materialize as materialize

__all__ = [
    "JsonDataError",
    "JsonDataService",
    "JsonDataStatus",
    "JsonEntity",
    "JsonValue",
    "materialize",
]
