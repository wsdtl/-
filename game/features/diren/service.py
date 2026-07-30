"""把敌人 JSON 生成一次性参战对象，不负责选择场景或结算玩家资产。"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Mapping

from game.content import GameContent
from game.features.loadout import (
    configure_battle_instances,
    direction_candidates,
    global_candidates,
    roll_loadout,
)
from game.rules import CombatantSnapshot


@dataclass(frozen=True)
class EnemyInstance:
    instance_id: str
    enemy_id: str
    kind: str
    rank: str
    level: int
    attributes: dict[str, float]
    weapon_attack: float
    direction_id: str | None
    technique_ids: tuple[str, ...]
    enchantment_ids: tuple[str, ...]
    gem_ids: tuple[str, ...]
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

    def spawn(
        self,
        enemy_id: str,
        *,
        seed: int,
        rank: str = "普通",
    ) -> EnemyInstance:
        key = str(enemy_id)
        definition = self.content.enemy_definitions[key]
        rng = random.Random(int(seed))
        grade_rng = random.Random(int(seed) ^ 0x6A09E667F3BCC909)
        loadout_rng = random.Random(int(seed) ^ 0xBB67AE8584CAA73B)
        kind = str(definition["类别"])
        enemy_rank = str(rank)
        if enemy_rank not in {"普通", "首领"}:
            raise ValueError(f"未知敌方修士构筑：{enemy_rank}")
        level = _roll_range(rng, definition["等级"])
        growth = (
            self.content.player["人物"]["每级成长"]
            if kind == "修士"
            else definition["每级成长"]
        )
        attributes = self.content.attributes_at_level(definition["属性"], growth, level)
        _apply_variation(rng, attributes, definition["实力波动"])
        loot = definition["掉落"]

        if kind == "修士":
            spirit_stones, inventory = _roll_item_pool(
                rng,
                grade_rng,
                loot,
                self.content,
            )
            strategy = definition["战斗策略"]
            weapon_attack = float(definition["本命武器"]["攻击"])
            loadout_rule = self.content.combination_rules["敌方修士构筑"][
                enemy_rank
            ]
            scope = str(loadout_rule["候选范围"])
            if scope == "随机方向":
                direction_id: str | None = loadout_rng.choice(
                    tuple(self.content.direction_definitions)
                )
                candidates = direction_candidates(self.content, direction_id)
            elif scope == "全池":
                direction_id = None
                candidates = global_candidates(
                    self.content,
                    loadout_rng,
                    theme_limit=int(loadout_rule["战术数量上限"]),
                )
            else:
                raise ValueError(f"未知敌方修士候选范围：{scope}")
            rolled = roll_loadout(
                self.content,
                loadout_rng,
                candidates=candidates,
                counts={
                    "功法": int(loadout_rule["功法位"]),
                    "附魔": int(loadout_rule["附魔位"]),
                    "宝石": int(loadout_rule["宝石位"]),
                },
                direction_id=direction_id,
            )
            techniques = configure_battle_instances(
                self.content,
                techniques=rolled.techniques,
                enchantments=rolled.enchantments,
                gems=rolled.gems,
                instance_prefix=f"enemy:{key}:{seed}",
            )
            technique_ids = tuple(str(value["功法"]) for value in rolled.techniques)
            enchantment_ids = tuple(str(value["名称"]) for value in rolled.enchantments)
            gem_ids = tuple(str(value["名称"]) for value in rolled.gems)
            fixed_drops: dict[str, int] = {}
            auto_medicine = rng.random() < float(strategy["用药概率"])
            medicine_threshold = float(strategy["用药阈值"])
        else:
            spirit_stones, fixed_drops = _roll_item_pool(
                rng,
                grade_rng,
                loot,
                self.content,
            )
            inventory = {}
            weapon_attack = 0.0
            direction_id = None
            technique_ids = ()
            enchantment_ids = ()
            gem_ids = ()
            techniques = ()
            auto_medicine = False
            medicine_threshold = 0.0

        return EnemyInstance(
            instance_id=f"enemy:{key}:{seed}",
            enemy_id=key,
            kind=kind,
            rank=enemy_rank,
            level=level,
            attributes=attributes,
            weapon_attack=weapon_attack,
            direction_id=direction_id,
            technique_ids=technique_ids,
            enchantment_ids=enchantment_ids,
            gem_ids=gem_ids,
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
    grade_rng: random.Random,
    definition: dict[str, Any],
    content: GameContent,
) -> tuple[int, dict[str, int]]:
    pool_files = list(definition["物品池"])
    if not pool_files:
        return _roll_range(rng, definition["灵石"]), {}
    item_ids = content.items_in_groups(pool_files)
    item_id = content.choose_item(item_ids, rng)
    grade_id = content.choose_grade(grade_rng)
    item = content.graded_item_definition(item_id, grade_id)
    return _roll_range(rng, definition["灵石"]), {str(item["名称"]): 1}


def _roll_range(rng: random.Random, value: int | list[int]) -> int:
    if isinstance(value, int):
        return value
    return rng.randint(int(value[0]), int(value[1]))


__all__ = ["EnemyFeature", "EnemyInstance"]
