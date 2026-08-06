"""角色核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class CharacterCreationError(RuntimeError):
    """角色创建无法完成。"""


class CharacterInputError(CharacterCreationError, ValueError):
    """创建输入不符合正式 JSON 规则。"""


class CharacterAlreadyExistsError(CharacterCreationError):
    """该用户已经拥有角色。"""


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


__all__ = [
    "CharacterAlreadyExistsError",
    "CharacterCreateCommand",
    "CharacterCreationError",
    "CharacterCreationResult",
    "CharacterInputError",
    "CharacterStatus",
]
