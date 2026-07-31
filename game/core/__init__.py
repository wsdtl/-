"""晓楠修仙公共核心微服务入口。"""

from .data import (
    JsonDataError as JsonDataError,
    JsonDataService as JsonDataService,
    JsonDataStatus as JsonDataStatus,
)
from .combat import (
    CombatService as CombatService,
    CombatStatus as CombatStatus,
    CombatantSnapshot as CombatantSnapshot,
)
from .pool import (
    ALLOW_REPEATS as ALLOW_REPEATS,
    EXPAND_DEDUPLICATED as EXPAND_DEDUPLICATED,
    PoolEntry as PoolEntry,
    PoolResult as PoolResult,
    PoolService as PoolService,
    PoolStatus as PoolStatus,
)


CORE_VERSION = "xiaonan.core.v1"
