"""先天灵宝收藏、槽位与规则介入的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.database import StateMutation


class InnateTreasureError(ValueError):
    """先天灵宝定义或人物灵宝状态不合法。"""


class InnateTreasureConflictError(InnateTreasureError):
    """先天灵宝收藏或槽位已经发生变化。"""


@dataclass(frozen=True)
class InnateTreasureStatus:
    initialized: bool
    treasure_count: int
    slot_count: int
    page_limit: int


@dataclass(frozen=True)
class InnateTreasureEffect:
    node: str
    ability: str
    values: Mapping[str, object]


@dataclass(frozen=True)
class InnateTreasure:
    treasure_id: str
    name: str
    authority: str
    description: str
    effect: InnateTreasureEffect


@dataclass(frozen=True)
class InnateTreasureCollection:
    user_id: str
    owned: tuple[InnateTreasure, ...]
    active: InnateTreasure | None
    version: int


@dataclass(frozen=True)
class InnateTreasureMutationPlan:
    treasure: InnateTreasure
    operation: StateMutation | None
    already_owned: bool = False


@dataclass(frozen=True)
class InnateTreasureActivation:
    treasure_id: str
    name: str
    authority: str
    summary: str


__all__ = [
    "InnateTreasure",
    "InnateTreasureActivation",
    "InnateTreasureCollection",
    "InnateTreasureConflictError",
    "InnateTreasureEffect",
    "InnateTreasureError",
    "InnateTreasureMutationPlan",
    "InnateTreasureStatus",
]
