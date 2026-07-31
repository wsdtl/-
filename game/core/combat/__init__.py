"""第二个公共核心微服务：战斗。"""

from .models import (
    BattleEvent as BattleEvent,
    BattleOutcome as BattleOutcome,
    CombatantResult as CombatantResult,
    CombatantSnapshot as CombatantSnapshot,
    StatusState as StatusState,
)
from .report import BattleReportParticipant as BattleReportParticipant
from .service import CombatService as CombatService, CombatStatus as CombatStatus


__all__ = [
    "BattleEvent",
    "BattleOutcome",
    "BattleReportParticipant",
    "CombatantResult",
    "CombatantSnapshot",
    "CombatService",
    "CombatStatus",
    "StatusState",
]
