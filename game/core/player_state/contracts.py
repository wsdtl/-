"""玩家状态核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class PlayerStateError(RuntimeError):
    """玩家状态无法完成请求。"""


class PlayerStateRuleError(PlayerStateError, ValueError):
    """玩家状态 JSON 或持久化快照不符合正式规则。"""


class PlayerStateConflictError(PlayerStateError):
    """当前状态不允许目标转换。"""


class PlayerStateCharacterMissingError(PlayerStateError):
    """用户尚未创建人物。"""


@dataclass(frozen=True)
class PlayerStateServiceStatus:
    initialized: bool
    initial_states: Mapping[str, str]
    state_count: int
    guard_rule_count: int


@dataclass(frozen=True)
class StateSlot:
    state_type: str
    state_id: str
    name: str
    context: Mapping[str, Any]


@dataclass(frozen=True)
class PlayerStateSnapshot:
    user_id: str
    states: Mapping[str, StateSlot]
    version: int
    updated_at: str


@dataclass(frozen=True)
class StateTransitionCommand:
    user_id: str
    request_id: str
    state_type: str
    target_state_id: str
    context: Mapping[str, Any] = field(default_factory=dict)
    expected_version: int | None = None


@dataclass(frozen=True)
class StateTransitionResult:
    user_id: str
    state_type: str
    previous_state_id: str
    current_state_id: str
    version: int
    replayed: bool


@dataclass(frozen=True)
class StateGuardResult:
    allowed: bool
    reason: str = ""
    current_states: Mapping[str, str] = field(default_factory=dict)


__all__ = [
    "PlayerStateCharacterMissingError",
    "PlayerStateConflictError",
    "PlayerStateError",
    "PlayerStateRuleError",
    "PlayerStateServiceStatus",
    "PlayerStateSnapshot",
    "StateGuardResult",
    "StateSlot",
    "StateTransitionCommand",
    "StateTransitionResult",
]
