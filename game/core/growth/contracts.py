"""人物、道侣与本命武器共用的成长计算契约。"""

from __future__ import annotations

from dataclasses import dataclass


class GrowthError(ValueError):
    """成长参数或正式规则无法完成计算。"""


@dataclass(frozen=True)
class GrowthStatus:
    initialized: bool
    realm_count: int
    maximum_level: int
    weapon_maximum_level: int


@dataclass(frozen=True)
class RealmDefinition:
    realm_id: str
    name: str
    minimum_level: int
    maximum_level: int
    next_realm_id: str = ""


@dataclass(frozen=True)
class ExperienceAdvance:
    level_before: int
    level_after: int
    experience_before: int
    experience_after: int
    experience_gained: int
    levels_gained: int
    capped: bool


@dataclass(frozen=True)
class WeaponAdvance:
    level_before: int
    level_after: int
    experience_before: int
    experience_after: int
    experience_gained: int
    stage_before: str
    stage_after: str
    open_slots_before: int
    open_slots_after: int


@dataclass(frozen=True)
class RandomCultivationBuild:
    seed: int
    techniques: tuple[str, ...]
    intents: tuple[str, ...]
    qi_patterns: tuple[str, ...]


__all__ = [
    "ExperienceAdvance",
    "GrowthError",
    "GrowthStatus",
    "RandomCultivationBuild",
    "RealmDefinition",
    "WeaponAdvance",
]
