"""轻量战斗内核的稳定数据与结算模块。"""

from .catalog import BattleReportCatalog as BattleReportCatalog
from .damage import (
    DamageBreakdown as DamageBreakdown,
    DamageEngine as DamageEngine,
    DamageRequest as DamageRequest,
    DamageResolution as DamageResolution,
)
from .mechanics import MechanismRuntime as MechanismRuntime
from .models import (
    BattleContext as BattleContext,
    BattleEvent as BattleEvent,
    BattleOutcome as BattleOutcome,
    CombatCatalog as CombatCatalog,
    CombatantResult as CombatantResult,
    CombatantSnapshot as CombatantSnapshot,
    Fighter as Fighter,
    RuleNode as RuleNode,
    Skill as Skill,
    StatusState as StatusState,
)
from .report import (
    BattleReportParticipant as BattleReportParticipant,
    build_battle_report as build_battle_report,
)
from .presentation import (
    build_battle_report_presentation as build_battle_report_presentation,
)
