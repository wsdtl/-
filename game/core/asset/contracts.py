"""玩家资产只读视图的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class AssetStateError(RuntimeError):
    """数据库中的玩家资产不符合当前 JSON 契约。"""


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


__all__ = [
    "AssetCategory",
    "AssetEntry",
    "AssetSnapshot",
    "AssetSortRules",
    "AssetStateError",
    "AssetStatus",
    "AssetSubcategory",
]
