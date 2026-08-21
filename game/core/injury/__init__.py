"""长期伤势核心微服务。"""

from .contracts import (
    InjuryChange,
    InjuryEntry,
    InjuryError,
    InjuryEvolution,
    InjurySource,
    InjuryState,
    InjuryStatus,
    InjurySummary,
    InjuryTreatment,
)
from .service import PLAYER_KEY, STATE_TYPE, InjuryService, companion_subject

__all__ = [
    "PLAYER_KEY",
    "STATE_TYPE",
    "InjuryChange",
    "InjuryEntry",
    "InjuryError",
    "InjuryEvolution",
    "InjuryService",
    "InjurySource",
    "InjuryState",
    "InjuryStatus",
    "InjurySummary",
    "InjuryTreatment",
    "companion_subject",
]
