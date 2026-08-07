"""角色核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class CharacterCreationError(RuntimeError):
    """角色创建无法完成。"""


class CharacterInputError(CharacterCreationError, ValueError):
    """创建输入不符合正式 JSON 规则。"""


class CharacterAlreadyExistsError(CharacterCreationError):
    """该用户已经拥有角色。"""


class CharacterNotFoundError(RuntimeError):
    """该用户尚未创建人物。"""


class CharacterStateError(RuntimeError):
    """已经保存的角色资产不符合当前正式规则。"""


@dataclass(frozen=True)
class CharacterStatus:
    initialized: bool
    role_name: str
    gender_count: int
    initial_item_count: int


@dataclass(frozen=True)
class CharacterCreateCommand:
    user_id: str
    request_id: str
    name: str
    gender: str
    birth_xy: tuple[int, int]


@dataclass(frozen=True)
class CharacterCreationResult:
    user_id: str
    name: str
    gender: str
    realm_id: str
    realm_name: str
    birth_xy: tuple[int, int]
    initial_items: tuple[tuple[str, str, int], ...]
    replayed: bool


@dataclass(frozen=True)
class EquippedContent:
    category: str
    slot: int
    content_id: str
    name: str
    grade: str = ""


@dataclass(frozen=True)
class WeaponProfile:
    name: str
    level: int
    experience: int
    attack: int | float
    stage: str
    open_law_slots: int
    equipped_laws: tuple[EquippedContent, ...]


@dataclass(frozen=True)
class InventorySummary:
    stack_count: int
    total_quantity: int


@dataclass(frozen=True)
class CharacterProfile:
    user_id: str
    name: str
    gender: str
    character_type: str
    realm_id: str
    realm_name: str
    level: int
    experience: int
    spirit_stones: int
    automatic_medicine: bool
    xy: tuple[int, int]
    attributes: tuple[tuple[str, int | float], ...]
    resources: tuple[tuple[str, int | float], ...]
    cultivation_slots: tuple[tuple[str, int], ...]
    equipped_content: tuple[EquippedContent, ...]
    weapon: WeaponProfile
    inventory: InventorySummary


__all__ = [
    "CharacterAlreadyExistsError",
    "CharacterCreateCommand",
    "CharacterCreationError",
    "CharacterCreationResult",
    "CharacterInputError",
    "CharacterNotFoundError",
    "CharacterProfile",
    "CharacterStateError",
    "CharacterStatus",
    "EquippedContent",
    "InventorySummary",
    "WeaponProfile",
]
