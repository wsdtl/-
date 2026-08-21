"""异步玩法生命周期的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

ACTIVITY_PHASES = frozenset(
    {"pending", "running", "ready", "settled", "terminated"}
)


@dataclass(frozen=True)
class ActivityLifecycleStatus:
    initialized: bool


@dataclass(frozen=True)
class ActivityFacts:
    """玩法从自己的持久化事实中投影出的最小生命周期信息。"""

    activity_type: str
    activity_id: str
    owner_id: str
    participant_user_ids: tuple[str, ...]
    settlement_user_ids: tuple[str, ...]
    phase: str
    started_at: datetime | None = None
    ends_at: datetime | None = None
    completed_at: datetime | None = None
    early_settlement: bool = False


@dataclass(frozen=True)
class ActivityLifecycle:
    activity_type: str
    activity_id: str
    owner_id: str
    participant_user_ids: tuple[str, ...]
    phase: str
    started_at: datetime | None
    ends_at: datetime | None
    completed_at: datetime | None
    remaining_seconds: int
    can_settle: bool


__all__ = [
    "ACTIVITY_PHASES",
    "ActivityFacts",
    "ActivityLifecycle",
    "ActivityLifecycleStatus",
]
