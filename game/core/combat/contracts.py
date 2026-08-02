"""战斗核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

BUILD_SECTIONS = frozenset({"功法", "附魔", "宝石"})


@dataclass(frozen=True)
class CombatStatus:
    initialized: bool
    mechanism_count: int
    ability_count: int
    event_count: int


@dataclass(frozen=True)
class CombatBuildRef:
    section: str
    identity: str
    instance_id: str = ""
    born_order: int = 0
    power_multiplier: float = 1.0


@dataclass(frozen=True)
class CombatantSpec:
    id: str
    name: str
    attributes: Mapping[str, float]
    level: int = 1
    kind: str = "修士"
    weapon_attack: float = 0.0
    build: tuple[CombatBuildRef, ...] = ()
    health: float | None = None
    spirit: float | None = None
    shield: float = 0.0
    statuses: tuple[Mapping[str, Any], ...] = ()
    cooldowns: Mapping[str, int] = field(default_factory=dict)
    inventory: Mapping[str, int] = field(default_factory=dict)
    auto_medicine: bool = False
    medicine_threshold: float = 0.3
    skill_cursor: int = 0
    owner_id: str = ""
    controller_id: str = ""
    form: str = "本相"
    forms: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    tactic: tuple[Mapping[str, Any], ...] = ()
    battle_profile: Mapping[str, Any] = field(default_factory=dict)
    battle_pills: tuple[str, ...] = ()


@dataclass(frozen=True)
class CombatantReportSpec:
    id: str
    title: str = ""
    color: str = ""
    moves: tuple[str, ...] = ()
    mechanisms: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CombatReportSpec:
    participants: tuple[CombatantReportSpec, ...] = ()
    scene: str = "青岚山演武台"
    generated_at: str | None = None
    include_presentation: bool = False


@dataclass(frozen=True)
class CombatRequest:
    left_team: tuple[CombatantSpec, ...]
    right_team: tuple[CombatantSpec, ...]
    seed: int
    action_limit: int
    share_left_inventory: bool = False
    report: CombatReportSpec | None = None


@dataclass(frozen=True)
class StatusResult:
    name: str
    category: str
    remaining_turns: int
    source: str
    source_name: str
    source_mechanism: str
    modifiers: Mapping[str, float]
    stacks: int
    max_stacks: int
    tags: tuple[str, ...]
    duration_unit: str
    action_limits: tuple[str, ...]
    effect_immunities: tuple[str, ...]
    listeners: tuple[Mapping[str, Any], ...]
    values: Mapping[str, Any]
    expire_with_source: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "名称": self.name,
            "类别": self.category,
            "剩余行动": self.remaining_turns,
            "来源": self.source,
            "来源名称": self.source_name,
            "来源机制": self.source_mechanism,
            "属性": dict(self.modifiers),
            "层数": self.stacks,
            "层数上限": self.max_stacks,
            "标签": list(self.tags),
            "持续单位": self.duration_unit,
            "行动限制": list(self.action_limits),
            "效果免疫": list(self.effect_immunities),
            "监听": [dict(value) for value in self.listeners],
            "记录": dict(self.values),
            "来源退场时移除": self.expire_with_source,
        }


@dataclass(frozen=True)
class BattleEvent:
    turn: int
    kind: str
    source: str
    target: str
    text: str
    amount: float = 0.0
    values: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    mechanism: str = ""
    source_id: str = ""
    target_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "text": self.text,
            "amount": self.amount,
            "values": dict(self.values),
            "tags": list(self.tags),
            "mechanism": self.mechanism,
            "source_id": self.source_id,
            "target_id": self.target_id,
        }


@dataclass(frozen=True)
class CombatantResult:
    id: str
    name: str
    attributes: Mapping[str, float]
    level: int
    kind: str
    health: float
    spirit: float
    shield: float
    statuses: tuple[StatusResult, ...]
    cooldowns: Mapping[str, int]
    inventory: Mapping[str, int]
    consumed_items: Mapping[str, int]
    skill_cursor: int
    form: str = "本相"
    owner_id: str = ""
    controller_id: str = ""
    counts_for_victory: bool = True
    battle_pills: tuple[str, ...] = ()

    @property
    def alive(self) -> bool:
        return self.health > 0


@dataclass(frozen=True)
class CombatResult:
    left: CombatantResult
    right: CombatantResult
    actions: int
    events: tuple[BattleEvent, ...]
    trigger_activations: int = 0
    left_team: tuple[CombatantResult, ...] = ()
    right_team: tuple[CombatantResult, ...] = ()
    report: Mapping[str, Any] | None = None
    presentation: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None

    @property
    def left_results(self) -> tuple[CombatantResult, ...]:
        return self.left_team or (self.left,)

    @property
    def right_results(self) -> tuple[CombatantResult, ...]:
        return self.right_team or (self.right,)

    @property
    def winner_side(self) -> str | None:
        left_alive = any(
            result.alive and result.counts_for_victory for result in self.left_results
        )
        right_alive = any(
            result.alive and result.counts_for_victory for result in self.right_results
        )
        if left_alive == right_alive:
            return None
        return "left" if left_alive else "right"

    @property
    def winner_id(self) -> str | None:
        winner_side = self.winner_side
        if winner_side is None:
            return None
        values = self.left_results if winner_side == "left" else self.right_results
        return next(
            (
                value.id
                for value in values
                if value.alive and value.counts_for_victory
            ),
            None,
        )

    @property
    def draw(self) -> bool:
        return self.winner_id is None


__all__ = [
    "BUILD_SECTIONS",
    "BattleEvent",
    "CombatBuildRef",
    "CombatReportSpec",
    "CombatRequest",
    "CombatResult",
    "CombatStatus",
    "CombatantResult",
    "CombatantReportSpec",
    "CombatantSpec",
    "StatusResult",
]
