"""玩家角色核心微服务。"""

from .contracts import (
    CharacterAlreadyExistsError,
    CharacterCreateCommand,
    CharacterCreationError,
    CharacterCreationResult,
    CharacterInputError,
    CharacterNotFoundError,
    CharacterProfile,
    CharacterStateError,
    CharacterStatus,
    EquippedContent,
    InventorySummary,
    WeaponProfile,
)
from .service import CharacterService

__all__ = [
    "CharacterAlreadyExistsError",
    "CharacterCreateCommand",
    "CharacterCreationError",
    "CharacterCreationResult",
    "CharacterInputError",
    "CharacterNotFoundError",
    "CharacterProfile",
    "CharacterService",
    "CharacterStateError",
    "CharacterStatus",
    "EquippedContent",
    "InventorySummary",
    "WeaponProfile",
]
