"""不依赖消息、数据库和具体玩法组件的纯规则。"""

from .combat import BattleEngine as BattleEngine
from .battle.models import (
    BattleEvent as BattleEvent,
    BattleOutcome as BattleOutcome,
    CombatCatalog as CombatCatalog,
    CombatantResult as CombatantResult,
    CombatantSnapshot as CombatantSnapshot,
    StatusState as StatusState,
)
