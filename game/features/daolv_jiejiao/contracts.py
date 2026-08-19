"""道侣结交玩法的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from game.core.asset import AssetGrade
from game.core.companion import (
    ActiveCompanion,
    CompanionDefinition,
    CompanionInstance,
    CompanionRelation,
)
from game.core.item_catalog import ItemDetail


class CompanionInteractionError(RuntimeError):
    """道侣结交请求无法完成。"""


class CompanionQueryError(CompanionInteractionError, ValueError):
    """道侣、物品、品级或数量查询无效。"""


class CompanionAccessError(CompanionInteractionError):
    """目标道侣当前不在玩家身边或不可交互。"""


class CompanionConflictError(CompanionInteractionError):
    """关系、同行位或库存版本已经变化。"""


@dataclass(frozen=True)
class CompanionAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class CompanionCopy:
    text: Mapping[str, Mapping[str, str]]
    icons: Mapping[str, str]


@dataclass(frozen=True)
class CompanionView:
    definition: CompanionDefinition
    relation: CompanionRelation
    active: ActiveCompanion | None
    has_relation: bool
    is_active: bool
    can_invite: bool


@dataclass(frozen=True)
class CompanionConversation:
    view: CompanionView
    line: str


@dataclass(frozen=True)
class CompanionGiftRequest:
    user_id: str
    request_id: str
    companion: str
    item: str
    grade: str
    quantity: int


@dataclass(frozen=True)
class CompanionGiftResult:
    view: CompanionView
    item: ItemDetail
    grade: AssetGrade | None
    quantity: int
    base_affection: Decimal
    accepted: bool
    preference: str
    preference_multiplier: Decimal
    dialogue: str
    affection_gain: Decimal
    affection_before: Decimal
    affection_after: Decimal
    reward_item: ItemDetail | None
    reward_grade: AssetGrade | None
    reward_quantity: int
    first_full: bool
    replayed: bool


@dataclass(frozen=True)
class CompanionInvitationRequest:
    user_id: str
    request_id: str
    companion: str


@dataclass(frozen=True)
class CompanionInvitationResult:
    view: CompanionView
    instance: CompanionInstance
    dialogue: str
    first_invitation: bool
    already_active: bool
    replayed: bool


@dataclass(frozen=True)
class CompanionFarewellRequest:
    user_id: str
    request_id: str
    companion: str


@dataclass(frozen=True)
class CompanionFarewellResult:
    definition: CompanionDefinition
    dialogue: str
    replayed: bool


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
    "CompanionInvitationRequest",
    "CompanionInvitationResult",
    "CompanionQueryError",
    "CompanionView",
]
