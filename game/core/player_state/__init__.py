"""玩家多类型状态核心微服务。"""

from .contracts import (
    PlayerStateCharacterMissingError,
    PlayerStateConflictError,
    PlayerStateError,
    PlayerStateRuleError,
    PlayerStateServiceStatus,
    PlayerStateSnapshot,
    PublicPlayerState,
    StateGuardResult,
    StateSlot,
    StateTransitionCommand,
    StateTransitionPlan,
    StateTransitionResult,
)
from .service import STATE_KEY, STATE_TYPE, PlayerStateService

__all__ = [
    "STATE_KEY",
    "STATE_TYPE",
    "PlayerStateCharacterMissingError",
    "PlayerStateConflictError",
    "PlayerStateError",
    "PlayerStateRuleError",
    "PlayerStateService",
    "PlayerStateServiceStatus",
    "PlayerStateSnapshot",
    "PublicPlayerState",
    "StateGuardResult",
    "StateSlot",
    "StateTransitionCommand",
    "StateTransitionPlan",
    "StateTransitionResult",
]
