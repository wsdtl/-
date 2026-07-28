"""把敌人 JSON 生成一次性参战对象，不负责选择场景或结算玩家资产。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random
from typing import Any, Mapping

from game.content import GameContent
from game.rules import CombatantSnapshot


@dataclass(frozen=True)
class EnemyInstance:
    instance_id: str
    enemy_id: str
    kind: str
    level: int
    attributes: dict[str, float]
    weapon_attack: float
    techniques: tuple[dict[str, Any], ...]
    spirit_stones: int
    inventory: dict[str, int]
    fixed_drops: dict[str, int]
    auto_medicine: bool
    medicine_threshold: float

    def battle_snapshot(self) -> CombatantSnapshot:
        return CombatantSnapshot(
            id=self.instance_id,
            name=self.enemy_id,
            attributes=self.attributes,
            level=self.level,
            kind=self.kind,
            weapon_attack=self.weapon_attack,
            techniques=self.techniques,
            inventory=self.inventory,
            auto_medicine=self.auto_medicine,
            medicine_threshold=self.medicine_threshold,
        )

    def defeated_items(self, remaining_inventory: Mapping[str, int]) -> dict[str, int]:
        if self.kind == "修士":
            return {
                str(key): int(quantity)
                for key, quantity in remaining_inventory.items()
                if int(quantity) > 0
            }
        return dict(self.fixed_drops)


class EnemyFeature:
    def __init__(self, content: GameContent) -> None:
        self.content = content

    def spawn(self, enemy_id: str, *, seed: int) -> EnemyInstance:
        key = str(enemy_id)
        definition = self.content.enemy_definitions[key]
        rng = random.Random(int(seed))
        kind = str(definition["类别"])
        level = _roll_range(rng, definition["等级"])
        growth = (
            self.content.player["人物"]["每级成长"]
            if kind == "修士"
            else definition["每级成长"]
        )
        attributes = self.content.attributes_at_level(definition["属性"], growth, level)
        _apply_variation(rng, attributes, definition["实力波动"])

        if kind == "修士":
            spirit_stones, inventory = _roll_item_pool(rng, definition["纳戒"])
            strategy = definition["战斗策略"]
            weapon_attack = float(definition["本命武器"]["攻击"])
            techniques = tuple(
                self.content.configured_battle_techniques(
                    definition["功法"],
                    instance_prefix=f"enemy:{key}:{seed}",
                )
            )
            fixed_drops: dict[str, int] = {}
            auto_medicine = rng.random() < float(strategy["用药概率"])
            medicine_threshold = float(strategy["用药阈值"])
        else:
            spirit_stones, fixed_drops = _roll_item_pool(rng, definition["掉落"])
            inventory = {}
            weapon_attack = 0.0
            techniques = ()
            auto_medicine = False
            medicine_threshold = 0.0

        return EnemyInstance(
            instance_id=f"enemy:{key}:{seed}",
            enemy_id=key,
            kind=kind,
            level=level,
            attributes=attributes,
            weapon_attack=weapon_attack,
            techniques=techniques,
            spirit_stones=spirit_stones,
            inventory=inventory,
            fixed_drops=fixed_drops,
            auto_medicine=auto_medicine,
            medicine_threshold=medicine_threshold,
        )


def _apply_variation(
    rng: random.Random,
    attributes: dict[str, float],
    definition: dict[str, Any],
) -> None:
    minimum, maximum = (int(value) for value in definition["倍率"])
    for key in definition["属性"]:
        name = str(key)
        attributes[name] = round(attributes[name] * rng.randint(minimum, maximum) / 100, 4)


def _roll_item_pool(
    rng: random.Random,
    definition: dict[str, Any],
) -> tuple[int, dict[str, int]]:
    items: Counter[str] = Counter()
    for value in definition["物品"]:
        if rng.random() <= float(value["概率"]):
            items[str(value["物品"])] += _roll_range(rng, value["数量"])
    return _roll_range(rng, definition["灵石"]), dict(items)


def _roll_range(rng: random.Random, value: int | list[int]) -> int:
    if isinstance(value, int):
        return value
    return rng.randint(int(value[0]), int(value[1]))


__all__ = ["EnemyFeature", "EnemyInstance"]
