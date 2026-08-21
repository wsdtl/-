"""长期伤势核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.combat import CombatStatusSpec
from game.core.database import StateMutation


class InjuryError(RuntimeError):
    """伤势定义或持久化事实不符合契约。"""


@dataclass(frozen=True)
class InjuryStatus:
    initialized: bool
    injury_count: int
    external_count: int
    self_generated_count: int


@dataclass(frozen=True)
class InjurySource:
    battle_id: str
    category: str
    source_id: str
    source_name: str


@dataclass(frozen=True)
class InjuryEntry:
    injury_id: str
    name: str
    category: str
    stacks: int
    acquired_order: int
    treatment_progress: int
    sources: tuple[InjurySource, ...]


@dataclass(frozen=True)
class InjuryState:
    user_id: str
    subject_key: str
    entries: tuple[InjuryEntry, ...]
    version: int


@dataclass(frozen=True)
class InjuryChange:
    injury_id: str
    name: str
    before_stacks: int
    after_stacks: int
    category: str


@dataclass(frozen=True)
class InjuryEvolution:
    state: InjuryState
    changes: tuple[InjuryChange, ...]


@dataclass(frozen=True)
class InjuryTreatment:
    state: InjuryState
    mutation: StateMutation | None
    changes: tuple[InjuryChange, ...]


@dataclass(frozen=True)
class InjurySummary:
    subject_key: str
    entries: tuple[Mapping[str, object], ...]


__all__ = [
    "CombatStatusSpec",
    "InjuryChange",
    "InjuryEntry",
    "InjuryError",
    "InjuryEvolution",
    "InjurySource",
    "InjuryState",
    "InjuryStatus",
    "InjurySummary",
    "InjuryTreatment",
]
