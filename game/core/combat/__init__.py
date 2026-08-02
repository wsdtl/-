"""第二个公共核心微服务：战斗。"""

from .contracts import (
    BattleEvent as BattleEvent,
)
from .contracts import (
    CombatantReportSpec as CombatantReportSpec,
)
from .contracts import (
    CombatantResult as CombatantResult,
)
from .contracts import (
    CombatantSpec as CombatantSpec,
)
from .contracts import (
    CombatBuildRef as CombatBuildRef,
)
from .contracts import (
    CombatReportSpec as CombatReportSpec,
)
from .contracts import (
    CombatRequest as CombatRequest,
)
from .contracts import (
    CombatResult as CombatResult,
)
from .contracts import (
    CombatStatus as CombatStatus,
)
from .contracts import (
    StatusResult as StatusResult,
)
from .service import CombatService as CombatService

__all__ = [
    "BattleEvent",
    "CombatBuildRef",
    "CombatReportSpec",
    "CombatRequest",
    "CombatResult",
    "CombatantResult",
    "CombatantReportSpec",
    "CombatantSpec",
    "CombatService",
    "CombatStatus",
    "StatusResult",
]
