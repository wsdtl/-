"""人物资产组件公开的稳定数据。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlayerState:
    user_id: str
    name: str
    level: int
    experience: int
    attributes: dict[str, float]
    health: float
    spirit: float
    stamina: float
    statuses: list[dict[str, Any]] = field(default_factory=list)
    auto_medicine: bool = True
    spirit_stones: int = 0
    breakthrough_pending: bool = False
    revision: int = 0

    def resource_maximum(self, resource: str) -> float:
        return max(0.0, float(self.attributes.get(f"{resource}上限", 0.0)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "level": self.level,
            "experience": self.experience,
            "attributes": dict(self.attributes),
            "health": self.health,
            "spirit": self.spirit,
            "stamina": self.stamina,
            "statuses": list(self.statuses),
            "auto_medicine": self.auto_medicine,
            "spirit_stones": self.spirit_stones,
            "breakthrough_pending": self.breakthrough_pending,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlayerState":
        return cls(
            user_id=str(value["user_id"]),
            name=str(value["name"]),
            level=int(value["level"]),
            experience=int(value["experience"]),
            attributes={str(key): float(amount) for key, amount in value["attributes"].items()},
            health=float(value["health"]),
            spirit=float(value["spirit"]),
            stamina=float(value["stamina"]),
            statuses=[dict(item) for item in value.get("statuses") or ()],
            auto_medicine=bool(value.get("auto_medicine", True)),
            spirit_stones=int(value.get("spirit_stones") or 0),
            breakthrough_pending=bool(value.get("breakthrough_pending")),
            revision=int(value.get("revision") or 0),
        )


@dataclass
class WeaponState:
    user_id: str
    name: str
    level: int
    experience: int
    attributes: dict[str, float]
    enchantments: list[dict[str, Any]] = field(default_factory=list)
    gems: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "level": self.level,
            "experience": self.experience,
            "attributes": dict(self.attributes),
            "enchantments": list(self.enchantments),
            "gems": list(self.gems),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WeaponState":
        return cls(
            user_id=str(value["user_id"]),
            name=str(value["name"]),
            level=int(value["level"]),
            experience=int(value["experience"]),
            attributes={str(key): float(amount) for key, amount in value["attributes"].items()},
            enchantments=[dict(item) for item in value.get("enchantments") or ()],
            gems=[dict(item) for item in value.get("gems") or ()],
        )


@dataclass(frozen=True)
class TechniqueState:
    instance_id: str
    user_id: str
    technique_id: str
    rarity_id: str
    affixes: tuple[dict[str, Any], ...]
    born_order: int
    equipped_slot: int | None
    score: int
    acquired_at: str


@dataclass
class AssetState:
    player: PlayerState
    weapon: WeaponState
    inventory: dict[str, int]
    techniques: list[TechniqueState]


@dataclass(frozen=True)
class InventoryEntry:
    category: str
    key: str
    name: str
    quantity: int
    score: int
    detail: str = ""
    equipped_slot: int | None = None


@dataclass(frozen=True)
class InventoryPage:
    category: str
    category_name: str
    page: int
    pages: int
    total: int
    entries: tuple[InventoryEntry, ...]


@dataclass(frozen=True)
class ExperienceResult:
    applied: int
    levels_gained: int
    locked: bool


@dataclass(frozen=True)
class ItemUseResult:
    status: str
    item_name: str = ""
    quantity: int = 0
    recovered: float = 0.0
    resource: str = ""


__all__ = [
    "AssetState",
    "ExperienceResult",
    "InventoryEntry",
    "InventoryPage",
    "ItemUseResult",
    "PlayerState",
    "TechniqueState",
    "WeaponState",
]
