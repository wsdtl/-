"""人物行为状态微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class ActivityError(RuntimeError):
    """人物状态无法完成请求。"""


class ActivityRuleError(ActivityError, ValueError):
    """人物状态 JSON 规则无效。"""


class ActivityConflictError(ActivityError):
    """当前人物状态不允许进行目标转换。"""


class ActivityCharacterMissingError(ActivityError):
    """用户尚未创建人物，无法读取行为状态。"""


@dataclass(frozen=True)
class ActivityServiceStatus:
    initialized: bool
    initial_status: str
    status_count: int
    access_rule_count: int


@dataclass(frozen=True)
class CharacterActivity:
    user_id: str
    name: str
    context: Mapping[str, Any]
    version: int
    updated_at: str


@dataclass(frozen=True)
class ActivityTransitionCommand:
    user_id: str
    request_id: str
    target: str
    context: Mapping[str, Any] = field(default_factory=dict)
    expected_version: int | None = None


@dataclass(frozen=True)
class ActivityTransitionResult:
    user_id: str
    previous: str
    current: str
    version: int
    replayed: bool


@dataclass(frozen=True)
class ActivityAccessResult:
    allowed: bool
    reason: str = ""
    current: str | None = None


__all__ = [
    "ActivityAccessResult",
    "ActivityCharacterMissingError",
    "ActivityConflictError",
    "ActivityError",
    "ActivityRuleError",
    "ActivityServiceStatus",
    "ActivityTransitionCommand",
    "ActivityTransitionResult",
    "CharacterActivity",
]
