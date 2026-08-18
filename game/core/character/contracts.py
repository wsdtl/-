"""角色核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.database import StateMutation


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


class CharacterCultivationError(CharacterStateError, ValueError):
    """人物培养请求不符合当前人物、道藏或本命武器状态。"""


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
class CharacterPublicProfile:
    user_id: str
    name: str
    gender: str
    realm_id: str
    realm_name: str
    level: int


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
    attributes: tuple[tuple[str, int | float], ...]
    resources: tuple[tuple[str, int | float], ...]
    cultivation_slots: tuple[tuple[str, int], ...]
    equipped_content: tuple[EquippedContent, ...]
    weapon: WeaponProfile
    inventory: InventorySummary


@dataclass(frozen=True)
class CharacterGrowthPlan:
    level_before: int
    level_after: int
    weapon_level_before: int
    weapon_level_after: int
    operations: tuple[StateMutation, ...]


@dataclass(frozen=True)
class CharacterRetreatPlan:
    experience_gained: int
    level_before: int
    level_after: int
    health: float
    spirit: float
    operation: StateMutation


@dataclass(frozen=True)
class CharacterEquipPlan:
    category: str
    slot: int
    content_id: str
    content_name: str
    grade_id: str
    replaced_content_id: str
    operation: StateMutation


@dataclass(frozen=True)
class CharacterBreakthroughPlan:
    realm_before: str
    realm_after: str
    realm_name_after: str
    medicine_id: str
    operation: StateMutation


@dataclass(frozen=True)
class CharacterLawPlan:
    slot: int
    law_id: str
    law_name: str
    replaced_law_id: str
    operation: StateMutation


@dataclass(frozen=True)
class CharacterBattlePlan:
    health: float
    spirit: float
    spirit_stones_delta: int
    weapon_experience_gained: int
    operations: tuple[StateMutation, ...]


__all__ = [
    "CharacterAlreadyExistsError",
    "CharacterBattlePlan",
    "CharacterBreakthroughPlan",
    "CharacterCreateCommand",
    "CharacterCreationError",
    "CharacterCreationResult",
    "CharacterCultivationError",
    "CharacterEquipPlan",
    "CharacterGrowthPlan",
    "CharacterInputError",
    "CharacterLawPlan",
    "CharacterNotFoundError",
    "CharacterProfile",
    "CharacterPublicProfile",
    "CharacterRetreatPlan",
    "CharacterStateError",
    "CharacterStatus",
    "EquippedContent",
    "InventorySummary",
    "WeaponProfile",
]
