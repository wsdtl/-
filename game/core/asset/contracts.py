"""玩家资产只读视图的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from game.core.database import StateMutation


class AssetStateError(RuntimeError):
    """数据库中的玩家资产不符合当前 JSON 契约。"""


class InventoryChangeError(AssetStateError):
    """普通物品库存无法完成指定增减。"""


@dataclass(frozen=True)
class AssetSubcategory:
    name: str


@dataclass(frozen=True)
class AssetCategory:
    name: str
    icon: str
    subcategories: tuple[AssetSubcategory, ...]


@dataclass(frozen=True)
class AssetEntry:
    category: str
    subcategory: str
    content_id: str
    instance_key: str
    name: str
    grade_id: str = ""
    grade_name: str = ""
    quantity: int = 1
    equipped_slots: tuple[str, ...] = ()
    material_total: int | None = None
    updated_at: str = ""


@dataclass(frozen=True)
class AssetSortRules:
    equipped_first: bool
    grade_descending: bool
    content_id_descending: bool
    holy_formation_newest_first: bool


@dataclass(frozen=True)
class AssetSnapshot:
    user_id: str
    categories: tuple[AssetCategory, ...]
    entries: tuple[AssetEntry, ...]
    page_limit: int
    sort_rules: AssetSortRules


@dataclass(frozen=True)
class AssetStatus:
    initialized: bool
    category_count: int
    subcategory_count: int
    page_limit: int


@dataclass(frozen=True)
class AssetGrade:
    grade_id: str
    name: str
    order: int
    ability_multiplier: Decimal
    price_multiplier: Decimal


@dataclass(frozen=True)
class InventoryStack:
    item_id: str
    item_name: str
    grade: AssetGrade
    quantity: int
    version: int


@dataclass(frozen=True)
class InventoryAdjustment:
    item_id: str
    grade_id: str
    quantity_delta: int


@dataclass(frozen=True)
class InventoryChange:
    item_id: str
    item_name: str
    grade: AssetGrade
    before_quantity: int
    after_quantity: int


@dataclass(frozen=True)
class InventoryMutationPlan:
    changes: tuple[InventoryChange, ...]
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CultivationOwnership:
    category: str
    content_id: str
    name: str
    grade: AssetGrade
    version: int


@dataclass(frozen=True)
class LawReserveStack:
    law_id: str
    name: str
    stage: str
    quantity: int
    version: int


@dataclass(frozen=True)
class LawReserveChangePlan:
    stack_before: LawReserveStack
    quantity_after: int
    operation: StateMutation


__all__ = [
    "AssetCategory",
    "AssetEntry",
    "AssetGrade",
    "AssetSnapshot",
    "AssetSortRules",
    "AssetStateError",
    "AssetStatus",
    "AssetSubcategory",
    "CultivationOwnership",
    "InventoryAdjustment",
    "InventoryChange",
    "InventoryChangeError",
    "InventoryMutationPlan",
    "InventoryStack",
    "LawReserveChangePlan",
    "LawReserveStack",
]
