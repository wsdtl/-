"""第三个公共核心微服务：资源池抽取。"""

from .models import PoolEntry as PoolEntry, PoolResult as PoolResult
from .service import (
    ALLOW_REPEATS as ALLOW_REPEATS,
    EXPAND_DEDUPLICATED as EXPAND_DEDUPLICATED,
    PoolService as PoolService,
    PoolStatus as PoolStatus,
)


__all__ = [
    "ALLOW_REPEATS",
    "EXPAND_DEDUPLICATED",
    "PoolEntry",
    "PoolResult",
    "PoolService",
    "PoolStatus",
]
