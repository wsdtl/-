"""探险核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class ExplorationError(RuntimeError):
    """探险无法完成请求。"""


class ExplorationStateError(ExplorationError):
    """探险持久化状态不符合契约。"""


class ExplorationConflictError(ExplorationError):
    """人物、位置或物资状态已发生冲突。"""


class ExplorationNotFinishedError(ExplorationError):
    """探险尚未到实际结束时间。"""


@dataclass(frozen=True)
class ExplorationStatus:
    initialized: bool
    seconds_per_battle: int
    maximum_battles: int
    action_limit: int


@dataclass(frozen=True)
class ExplorationStartCommand:
    owner_user_id: str
    request_id: str
    participant_user_ids: tuple[str, ...]
    seed: int | None = None
    started_at: datetime | None = None


@dataclass(frozen=True)
class ExplorationStarted:
    session_id: str
    location_name: str
    participant_count: int
    formal_unit_count: int
    battle_count: int
    started_at: datetime
    ends_at: datetime
    replayed: bool


@dataclass(frozen=True)
class ExplorationProgress:
    session_id: str
    location_name: str
    unlocked_battles: int
    total_battles: int
    remaining_seconds: int
    ended: bool
    surviving_allies: int
    defeated_enemies: int
    spirit_stones: int
    item_quantity: int


@dataclass(frozen=True)
class ExplorationCharacterSummary:
    name: str
    companion: bool
    health: float
    spirit: float
    alive: bool
    weapon_experience: int


@dataclass(frozen=True)
class ExplorationUserSummary:
    user_id: str
    character_name: str
    characters: tuple[ExplorationCharacterSummary, ...]
    consumed: tuple[tuple[str, str, int], ...]
    drops: tuple[tuple[str, str, int], ...]
    spirit_stones: int


@dataclass(frozen=True)
class ExplorationSettlement:
    session_id: str
    location_name: str
    battle_count: int
    defeated_enemies: int
    participant_count: int
    total_spirit_stones: int
    total_item_quantity: int
    users: tuple[ExplorationUserSummary, ...]
    settled_at: datetime
    replayed: bool


__all__ = [
    "ExplorationCharacterSummary",
    "ExplorationConflictError",
    "ExplorationError",
    "ExplorationNotFinishedError",
    "ExplorationProgress",
    "ExplorationSettlement",
    "ExplorationStartCommand",
    "ExplorationStarted",
    "ExplorationStateError",
    "ExplorationStatus",
    "ExplorationUserSummary",
]
