"""队伍核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class TeamError(RuntimeError):
    """队伍操作无法完成。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TeamRuleError(TeamError, ValueError):
    """队伍 JSON 或持久化事实不符合规则。"""


class TeamConflictError(TeamError):
    """队伍事实在操作期间已经改变。"""


@dataclass(frozen=True)
class TeamServiceStatus:
    initialized: bool
    maximum_players: int
    invitation_seconds: int


@dataclass(frozen=True)
class TeamSnapshot:
    team_id: str
    leader_user_id: str
    member_user_ids: tuple[str, ...]
    version: int
    updated_at: str


@dataclass(frozen=True)
class TeamMembership:
    user_id: str
    role: str
    team: TeamSnapshot


@dataclass(frozen=True)
class TeamInvitation:
    inviter_user_id: str
    target_user_id: str
    team_id: str
    expires_at: datetime
    version: int
    expired: bool


@dataclass(frozen=True)
class PublicTeamState:
    user_id: str
    grouped: bool
    member_count: int


__all__ = [
    "PublicTeamState",
    "TeamConflictError",
    "TeamError",
    "TeamInvitation",
    "TeamMembership",
    "TeamRuleError",
    "TeamServiceStatus",
    "TeamSnapshot",
]
