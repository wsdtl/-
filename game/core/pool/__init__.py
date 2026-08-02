"""第三个公共核心微服务：资源池抽取。"""

from .contracts import (
    ALLOW_REPEATS as ALLOW_REPEATS,
)
from .contracts import (
    EXPAND_DEDUPLICATED as EXPAND_DEDUPLICATED,
)
from .contracts import (
    PoolEntry as PoolEntry,
)
from .contracts import (
    PoolRequest as PoolRequest,
)
from .contracts import (
    PoolResult as PoolResult,
)
from .contracts import (
    PoolStatus as PoolStatus,
)
from .service import PoolService as PoolService

__all__ = [
    "ALLOW_REPEATS",
    "EXPAND_DEDUPLICATED",
    "PoolEntry",
    "PoolRequest",
    "PoolResult",
    "PoolService",
    "PoolStatus",
]
