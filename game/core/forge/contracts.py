"""炼器微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class ForgeError(ValueError):
    """器律、铸法、选材或本命武器状态不符合炼器规则。"""


@dataclass(frozen=True)
class ForgeMaterial:
    item_id: str
    grade: str


@dataclass(frozen=True)
class ForgeVeinRequirement:
    vein: str
    count: int


@dataclass(frozen=True)
class ForgeMethod:
    name: str
    tier: str
    description: str
    requirements: tuple[ForgeVeinRequirement, ...]

    @property
    def slot_count(self) -> int:
        return sum(value.count for value in self.requirements)


@dataclass(frozen=True)
class WeaponTier:
    name: str
    minimum_level: int
    maximum_level: int
    open_slots: int
    guide_count: int
    minimum_mineral_slots: int
    maximum_mineral_slots: int
    side_substitution_limit: int
    minimum_guide_grade: str
    minimum_mineral_grade: str


@dataclass(frozen=True)
class ForgeLawDefinition:
    identity: str
    name: str
    tier: str
    forge_method: str
    guide_veins: tuple[str, ...]
    mechanism_ids: tuple[str, ...]


@dataclass(frozen=True)
class WeaponState:
    level: int
    experience: int = 0
    laws: tuple[str | None, ...] = (None, None, None, None)


@dataclass(frozen=True)
class WeaponProfile:
    level: int
    experience: int
    tier: str
    attack: float
    open_slots: int
    laws: tuple[str | None, ...]

    @property
    def equipped_laws(self) -> tuple[str, ...]:
        return tuple(value for value in self.laws[: self.open_slots] if value is not None)


@dataclass(frozen=True)
class ForgeRequest:
    law_id: str
    slot: int
    weapon: WeaponState
    guides: tuple[ForgeMaterial, ...]
    auxiliaries: tuple[ForgeMaterial, ...]


@dataclass(frozen=True)
class ForgeAllocation:
    material: ForgeMaterial
    required_vein: str
    mode: str


@dataclass(frozen=True)
class ForgePlan:
    law: ForgeLawDefinition
    guides: tuple[ForgeMaterial, ...]
    allocations: tuple[ForgeAllocation, ...]
    slot: int
    replaced_law_id: str | None
    weapon: WeaponState


@dataclass(frozen=True)
class ForgeStatus:
    initialized: bool
    law_count: int
    method_count: int
    mineral_pool_count: int
    beast_pool_count: int
    mineral_count: int
    beast_treasure_count: int


__all__ = [
    "ForgeAllocation",
    "ForgeError",
    "ForgeLawDefinition",
    "ForgeMaterial",
    "ForgeMethod",
    "ForgePlan",
    "ForgeRequest",
    "ForgeStatus",
    "ForgeVeinRequirement",
    "WeaponProfile",
    "WeaponState",
    "WeaponTier",
]
