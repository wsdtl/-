"""宗门灵藏与万珍殿的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.database import SharedEntityMutation


class SectAssetError(RuntimeError):
    """宗门公共资产无法完成当前操作。"""


class SectAssetConflictError(SectAssetError):
    """宗门或相关资产在事务期间已经变化。"""


@dataclass(frozen=True)
class SectAssetStatus:
    initialized: bool
    material_categories: tuple[str, ...]
    product_categories: tuple[str, ...]


@dataclass(frozen=True)
class SectAssetEntry:
    entry_key: str
    category: str
    content_id: str
    name: str
    grade_id: str
    grade_name: str
    quantity: int
    materials: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class SectAssetVault:
    sect_id: str
    name: str
    spirit_stones: int
    entries: tuple[SectAssetEntry, ...]


@dataclass(frozen=True)
class SectAssetTransfer:
    vault: str
    action: str
    entry: SectAssetEntry | None
    spirit_stones: int
    replayed: bool


@dataclass(frozen=True)
class SectMaterialCost:
    category: str
    content_id: str
    grade_id: str
    quantity: int


@dataclass(frozen=True)
class SectProductGain:
    category: str
    content_id: str
    grade_id: str = ""
    quantity: int = 1
    materials: tuple[tuple[str, int], ...] = ()
    instance_key: str = ""


@dataclass(frozen=True)
class SectProductionAssetPlan:
    operations: tuple[SharedEntityMutation, ...]
    spirit_stones_before: int
    spirit_stones_after: int
    product_entry: SectAssetEntry | None


__all__ = [
    "SectAssetConflictError",
    "SectAssetEntry",
    "SectAssetError",
    "SectAssetStatus",
    "SectAssetTransfer",
    "SectAssetVault",
    "SectMaterialCost",
    "SectProductGain",
    "SectProductionAssetPlan",
]
