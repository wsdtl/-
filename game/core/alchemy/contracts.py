"""炼药微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.combat import CombatStatusSpec


class AlchemyError(ValueError):
    """丹方、炉法或选材不符合正式炼药规则。"""


@dataclass(frozen=True)
class AlchemyMaterial:
    item_id: str
    grade: str


@dataclass(frozen=True)
class VeinRequirement:
    vein: str
    count: int


@dataclass(frozen=True)
class FurnaceMethod:
    name: str
    description: str
    requirements: tuple[VeinRequirement, ...]


@dataclass(frozen=True)
class RecipeDefinition:
    identity: str
    name: str
    strength: int
    difficulty: int
    minimum_guide_grade: str
    minimum_auxiliary_grade: str
    guide_pool: str
    furnace_method: str
    output_item_id: str
    output_count: int


@dataclass(frozen=True)
class AlchemyRequest:
    recipe_id: str
    guides: tuple[AlchemyMaterial, ...]
    auxiliaries: tuple[AlchemyMaterial, ...]


@dataclass(frozen=True)
class MaterialAllocation:
    material: AlchemyMaterial
    required_vein: str
    mode: str


@dataclass(frozen=True)
class AlchemyGradeBasis:
    minimum_guide_grade: str
    minimum_auxiliary_grade: str
    guide_grades: tuple[str, ...]
    auxiliary_grades: tuple[str, ...]


@dataclass(frozen=True)
class AlchemyPlan:
    recipe: RecipeDefinition
    guides: tuple[AlchemyMaterial, ...]
    allocations: tuple[MaterialAllocation, ...]
    output_item_id: str
    output_count: int
    output_grade: str
    grade_basis: AlchemyGradeBasis


@dataclass(frozen=True)
class PreparedBattlePills:
    item_ids: tuple[str, ...]
    used_slots: int
    statuses: tuple[CombatStatusSpec, ...]


@dataclass(frozen=True)
class AlchemyStatus:
    initialized: bool
    recipe_count: int
    furnace_method_count: int
    material_pool_count: int
    guide_count: int


__all__ = [
    "AlchemyError",
    "AlchemyGradeBasis",
    "AlchemyMaterial",
    "AlchemyPlan",
    "AlchemyRequest",
    "AlchemyStatus",
    "FurnaceMethod",
    "MaterialAllocation",
    "PreparedBattlePills",
    "RecipeDefinition",
    "VeinRequirement",
]
