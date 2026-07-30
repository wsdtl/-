"""战斗状态、输入目录与结构化输出。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import random
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from game.rules.combat import BattleEngine


@dataclass(frozen=True)
class CombatCatalog:
    """运行期战斗 JSON；核心只执行这里登记并已校验的机制。"""

    attributes: Mapping[str, Mapping[str, Any]]
    mechanisms: Mapping[str, Mapping[str, Any]]
    abilities: Mapping[str, Mapping[str, Any]]
    events: frozenset[str]
    resources: Mapping[str, Mapping[str, Any]]
    damage_rules: Mapping[str, Any]
    action_rules: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "CombatCatalog":
        source = value or {}
        return cls(
            attributes=dict(source.get("属性") or {}),
            mechanisms=dict(source.get("机制") or {}),
            abilities=dict(source.get("原子能力") or {}),
            events=frozenset(str(item) for item in source.get("事件") or ()),
            resources=dict(source.get("资源") or {}),
            damage_rules=dict(source.get("伤害规则") or {}),
            action_rules=dict(source.get("行动规则") or {}),
        )

    def require_mechanism(self, key: str) -> Mapping[str, Any]:
        try:
            return self.mechanisms[str(key)]
        except KeyError as exc:
            raise ValueError(f"战斗核心未登记机制：{key}") from exc

    def parse_node(self, value: Mapping[str, Any]) -> "RuleNode":
        ability = str(value.get("能力") or "")
        try:
            definition = self.abilities[ability]
        except KeyError as exc:
            raise ValueError(f"战斗核心未登记原子能力：{ability or '<空>'}") from exc
        return RuleNode(
            ability=ability,
            executor=str(definition.get("执行器") or ""),
            category=str(definition.get("类别") or ""),
            values=value,
        )

    def require_node(self, key: str) -> "RuleNode":
        return self.parse_node(self.require_mechanism(key))


@dataclass(frozen=True)
class RuleNode:
    """由通用解析器从能力 JSON 得到的运行期节点。"""

    ability: str
    executor: str
    category: str
    values: Mapping[str, Any]


@dataclass
class StatusState:
    """可跨连续遭遇保存的状态快照。"""

    name: str
    category: str
    remaining_turns: int
    source: str = ""
    source_name: str = ""
    source_mechanism: str = ""
    source_attack: float = 0.0
    flat_damage: float = 0.0
    damage_attack_ratio: float = 0.0
    modifiers: dict[str, float] = field(default_factory=dict)
    stacks: int = 1
    max_stacks: int = 1
    tags: tuple[str, ...] = ()
    damage_form: str = "持续"
    defense_rule: str = "无视防御"
    can_critical: bool = False
    can_block: bool = False
    duration_unit: str = "状态承受者行动"
    action_limits: tuple[str, ...] = ()
    effect_immunities: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StatusState":
        return cls(
            name=str(value.get("名称") or "").strip(),
            category=str(value.get("类别") or "中性").strip(),
            remaining_turns=max(0, int(value.get("剩余回合") or 0)),
            source=str(value.get("来源") or "").strip(),
            source_name=str(value.get("来源名称") or "").strip(),
            source_mechanism=str(value.get("来源机制") or "").strip(),
            source_attack=float(value.get("来源攻击") or 0),
            flat_damage=float(value.get("固定伤害") or 0),
            damage_attack_ratio=float(value.get("攻击伤害比例") or 0),
            modifiers={
                str(key): float(amount)
                for key, amount in dict(value.get("属性修正") or {}).items()
            },
            stacks=max(1, int(value.get("层数") or 1)),
            max_stacks=max(1, int(value.get("层数上限") or 1)),
            tags=tuple(str(item) for item in value.get("标签") or ()),
            damage_form=str(value.get("伤害形式") or "持续"),
            defense_rule=str(value.get("防御规则") or "无视防御"),
            can_critical=bool(value.get("能否暴击", False)),
            can_block=bool(value.get("能否格挡", False)),
            duration_unit=str(value.get("持续单位") or "状态承受者行动"),
            action_limits=tuple(str(item) for item in value.get("行动限制") or ()),
            effect_immunities=tuple(str(item) for item in value.get("效果免疫") or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "名称": self.name,
            "类别": self.category,
            "剩余回合": self.remaining_turns,
            "来源": self.source,
            "来源名称": self.source_name,
            "来源机制": self.source_mechanism,
            "来源攻击": self.source_attack,
            "固定伤害": self.flat_damage,
            "攻击伤害比例": self.damage_attack_ratio,
            "属性修正": dict(self.modifiers),
            "层数": self.stacks,
            "层数上限": self.max_stacks,
            "标签": list(self.tags),
            "伤害形式": self.damage_form,
            "防御规则": self.defense_rule,
            "能否暴击": self.can_critical,
            "能否格挡": self.can_block,
            "持续单位": self.duration_unit,
            "行动限制": list(self.action_limits),
            "效果免疫": list(self.effect_immunities),
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
class CombatantSnapshot:
    """任意参战者进入战斗时的完整快照。"""

    id: str
    name: str
    attributes: Mapping[str, float]
    level: int = 1
    kind: str = "修士"
    weapon_attack: float = 0.0
    techniques: tuple[Mapping[str, Any], ...] = ()
    health: float | None = None
    spirit: float | None = None
    shield: float = 0.0
    statuses: tuple[Mapping[str, Any], ...] = ()
    cooldowns: Mapping[str, int] = field(default_factory=dict)
    inventory: Mapping[str, int] = field(default_factory=dict)
    auto_medicine: bool = False
    medicine_threshold: float = 0.3
    skill_cursor: int = 0
    charge_progress: Mapping[str, int] = field(default_factory=dict)
    charging_skill: str = ""


@dataclass(frozen=True)
class CombatantResult:
    """一名参战者离开战斗时可继续持久化的状态。"""

    id: str
    name: str
    attributes: Mapping[str, float]
    level: int
    kind: str
    health: float
    spirit: float
    shield: float
    statuses: tuple[StatusState, ...]
    cooldowns: Mapping[str, int]
    inventory: Mapping[str, int]
    consumed_items: Mapping[str, int]
    skill_cursor: int
    charge_progress: Mapping[str, int] = field(default_factory=dict)
    charging_skill: str = ""

    @property
    def alive(self) -> bool:
        return self.health > 0


@dataclass(frozen=True)
class BattleOutcome:
    left: CombatantResult
    right: CombatantResult
    actions: int
    events: tuple[BattleEvent, ...]
    trigger_activations: int = 0
    left_team: tuple[CombatantResult, ...] = ()
    right_team: tuple[CombatantResult, ...] = ()

    @property
    def left_results(self) -> tuple[CombatantResult, ...]:
        return self.left_team or (self.left,)

    @property
    def right_results(self) -> tuple[CombatantResult, ...]:
        return self.right_team or (self.right,)

    @property
    def winner_side(self) -> str | None:
        left_alive = any(result.alive for result in self.left_results)
        right_alive = any(result.alive for result in self.right_results)
        if left_alive == right_alive:
            return None
        return "left" if left_alive else "right"

    @property
    def winner_id(self) -> str | None:
        if self.winner_side == "left":
            return next(result.id for result in self.left_results if result.alive)
        if self.winner_side == "right":
            return next(result.id for result in self.right_results if result.alive)
        return None

    @property
    def draw(self) -> bool:
        return self.winner_id is None


@dataclass
class Fighter:
    id: str
    name: str
    attributes: dict[str, float]
    health: float
    spirit: float
    shield: float = 0.0
    statuses: list[StatusState] = field(default_factory=list)
    skills: tuple[Skill, ...] = ()
    passives: tuple[dict[str, Any], ...] = ()
    cooldowns: dict[str, int] = field(default_factory=dict)
    inventory: dict[str, int] = field(default_factory=dict)
    auto_medicine: bool = False
    medicine_threshold: float = 0.3
    consumed_items: dict[str, int] = field(default_factory=dict)
    skill_cursor: int = 0
    current_skill: str = ""
    charge_progress: dict[str, int] = field(default_factory=dict)
    charging_skill: str = ""
    level: int = 1
    kind: str = "修士"

    def value(self, key: str, default: float = 0.0) -> float:
        result = float(self.attributes.get(key, default))
        for status in self.statuses:
            result += float(status.modifiers.get(key, 0.0)) * max(1, status.stacks)
        return result

    @property
    def alive(self) -> bool:
        return self.health > 0

    @property
    def health_max(self) -> float:
        return max(1.0, self.value("血气上限", 1.0))

    @property
    def spirit_max(self) -> float:
        return max(0.0, self.value("精神上限", 0.0))

    @property
    def shield_max(self) -> float:
        return max(0.0, self.value("护盾上限", 0.0))


@dataclass(frozen=True)
class Skill:
    key: str
    name: str
    born_order: int
    release_order: int
    multiplier: float
    spirit_cost: float
    cooldown_turns: int
    charge_turns: int = 0
    effects: tuple[Mapping[str, Any], ...] = ()


@dataclass
class BattleContext:
    rng: random.Random
    left: Fighter
    right: Fighter
    item_definitions: dict[str, dict[str, Any]]
    left_team: tuple[Fighter, ...] = ()
    right_team: tuple[Fighter, ...] = ()
    events: list[BattleEvent] = field(default_factory=list)
    action_number: int = 0
    engine: "BattleEngine | None" = None
    trigger_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    battle_trigger_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    event_depth: int = 0
    action_progress: dict[str, float] = field(default_factory=dict)
    mechanism_counters: dict[tuple[str, str], float] = field(default_factory=dict)
    additional_action_counts: dict[str, int] = field(default_factory=dict)
    current_mechanism: str = ""
    pending_fatal_guards: dict[str, tuple[str, float, Mapping[str, Any]]] = field(default_factory=dict)
    trigger_stack: set[tuple[str, str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.left_team:
            self.left_team = (self.left,)
        if not self.right_team:
            self.right_team = (self.right,)
        if self.left_team[0] is not self.left or self.right_team[0] is not self.right:
            raise ValueError("队伍首位必须与左右主参战者一致")

    @property
    def fighters(self) -> tuple[Fighter, ...]:
        return self.left_team + self.right_team

    @property
    def both_sides_alive(self) -> bool:
        return any(value.alive for value in self.left_team) and any(
            value.alive for value in self.right_team
        )

    def side_index(self, fighter: Fighter) -> int:
        if any(fighter is value for value in self.left_team):
            return 0
        if any(fighter is value for value in self.right_team):
            return 1
        raise ValueError("参战者不属于当前战斗")

    def opponent_of(self, fighter: Fighter) -> Fighter:
        if any(fighter is value for value in self.left_team):
            candidates = tuple(value for value in self.right_team if value.alive)
        elif any(fighter is value for value in self.right_team):
            candidates = tuple(value for value in self.left_team if value.alive)
        else:
            raise ValueError("参战者不属于当前战斗")
        if not candidates:
            raise ValueError("对方阵营已无存活参战者")
        return candidates[0] if len(candidates) == 1 else self.rng.choice(candidates)

    def fighter_by_id(self, fighter_id: str) -> Fighter | None:
        return next((fighter for fighter in self.fighters if fighter.id == fighter_id), None)

    def event(
        self,
        kind: str,
        source: Fighter,
        target: Fighter,
        text: str,
        amount: float = 0.0,
        *,
        values: Mapping[str, Any] | None = None,
        tags: tuple[str, ...] = (),
        mechanism: str = "",
        dispatch: bool = True,
    ) -> None:
        event_values = dict(values or {})
        self.events.append(
            BattleEvent(
                self.action_number,
                kind,
                source.name,
                target.name,
                text,
                round(float(amount), 3),
                event_values,
                tuple(tags),
                mechanism,
                source.id,
                target.id,
            )
        )
        if dispatch and self.engine is not None:
            self.engine._dispatch_event(
                self,
                kind=kind,
                source=source,
                target=target,
                amount=float(amount),
                values=event_values,
                tags=tuple(tags),
            )


__all__ = [
    "BattleContext",
    "BattleEvent",
    "BattleOutcome",
    "CombatCatalog",
    "CombatantResult",
    "CombatantSnapshot",
    "Fighter",
    "RuleNode",
    "Skill",
    "StatusState",
]
