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
from .character import (
    resolve_level_tier as resolve_level_tier,
    resolve_tiered_character as resolve_tiered_character,
)
