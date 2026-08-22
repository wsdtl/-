"""敌人实例核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.combat import CombatantSpec


@dataclass(frozen=True)
class EnemyStatus:
    initialized: bool
    enemy_count: int


@dataclass(frozen=True)
class EnemyDrop:
    item_id: str
    grade_id: str
    quantity: int


@dataclass(frozen=True)
class EnemyReward:
    spirit_stones: int
    weapon_experience: int
    drops: tuple[EnemyDrop, ...]


@dataclass(frozen=True)
class EnemyInstance:
    name: str
    combatant: CombatantSpec
    reward: EnemyReward


@dataclass(frozen=True)
class EnemyGroup:
    """一次独立抽取的敌方编组。"""

    group_id: str
    combatants: tuple[EnemyInstance, ...]
    primary_ids: tuple[str, ...]


__all__ = ["EnemyDrop", "EnemyGroup", "EnemyInstance", "EnemyReward", "EnemyStatus"]
