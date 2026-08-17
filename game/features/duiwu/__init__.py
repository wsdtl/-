"""玩家队伍玩法微服务。"""

from .contracts import (
    TeamAction,
    TeamCopy,
    TeamFeatureError,
    TeamInvitationView,
    TeamMemberView,
    TeamOperationResult,
    TeamPage,
)
from .service import TeamFeature

__all__ = [
    "TeamAction",
    "TeamCopy",
    "TeamFeature",
    "TeamFeatureError",
    "TeamInvitationView",
    "TeamMemberView",
    "TeamOperationResult",
    "TeamPage",
]
