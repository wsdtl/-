"""物品定义微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class ItemDataError(ValueError):
    """物品定义或查询不符合正式 JSON 契约。"""


@dataclass(frozen=True)
class ItemCategory:
    name: str
    stackable: bool


@dataclass(frozen=True)
class ItemBattleState:
    name: str
    category: str
    remaining_actions: int
    duration_unit: str
    modifiers: tuple[tuple[str, float], ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ItemUseEffect:
    effect_type: str
    executor: str
    resource: str | None = None
    experience_target: str | None = None
    recovery_percent: int | None = None
    experience: int | None = None
    battle_mechanisms: tuple[str, ...] = ()
    battle_state: ItemBattleState | None = None
    target_realm_id: str | None = None
    permanent_attributes: tuple[tuple[str, float], ...] = ()
    build_sections: tuple[str, ...] = ()
    preserve_build_count: bool | None = None
    attribute_scope: str | None = None
    attribute_choice_count: int | None = None
    pure_breakthrough_only: bool | None = None
    repeated_correction_allowed: bool | None = None


@dataclass(frozen=True)
class ItemDefinition:
    identity: str
    category: str
    name: str
    description: str
    weight: int
    reference_price: int
    source_pool: str
    stackable: bool
    use_effect: ItemUseEffect | None
    strength: int | None = None


@dataclass(frozen=True)
class ItemMedicineDefinition:
    """战斗可消费的恢复丹快照；不暴露物品 JSON。"""

    identity: str
    resource: str
    recovery_percent: int


@dataclass(frozen=True)
class ItemStatus:
    initialized: bool
    category_count: int
    item_count: int
    usable_item_count: int


__all__ = [
    "ItemBattleState",
    "ItemCategory",
    "ItemDataError",
    "ItemDefinition",
    "ItemMedicineDefinition",
    "ItemStatus",
    "ItemUseEffect",
]
