"""人物行为状态核心微服务。"""

from .contracts import (
    ActivityAccessResult,
    ActivityCharacterMissingError,
    ActivityConflictError,
    ActivityError,
    ActivityRuleError,
    ActivityServiceStatus,
    ActivityTransitionCommand,
    ActivityTransitionResult,
    CharacterActivity,
)
from .service import STATE_KEY, STATE_TYPE, ActivityService

__all__ = [
    "STATE_KEY",
    "STATE_TYPE",
    "ActivityAccessResult",
    "ActivityCharacterMissingError",
    "ActivityConflictError",
    "ActivityError",
    "ActivityRuleError",
    "ActivityService",
    "ActivityServiceStatus",
    "ActivityTransitionCommand",
    "ActivityTransitionResult",
    "CharacterActivity",
]
