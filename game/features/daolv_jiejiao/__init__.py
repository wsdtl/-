"""道侣结交玩法微服务。"""

from .contracts import (
    CompanionAccessError,
    CompanionAction,
    CompanionConflictError,
    CompanionConversation,
    CompanionCopy,
    CompanionFarewellRequest,
    CompanionFarewellResult,
    CompanionGiftRequest,
    CompanionGiftResult,
    CompanionInteractionError,
    CompanionInvitationRequest,
    CompanionInvitationResult,
    CompanionQueryError,
    CompanionView,
)
from .service import CompanionInteractionFeature

__all__ = [
    "CompanionAccessError",
    "CompanionAction",
    "CompanionConflictError",
    "CompanionConversation",
    "CompanionCopy",
    "CompanionFarewellRequest",
    "CompanionFarewellResult",
    "CompanionGiftRequest",
    "CompanionGiftResult",
    "CompanionInteractionError",
    "CompanionInteractionFeature",
    "CompanionInvitationRequest",
    "CompanionInvitationResult",
    "CompanionQueryError",
    "CompanionView",
]
