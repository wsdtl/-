"""本地驱动器事件。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..context import (
    CONVERSATION_GROUP,
    CONVERSATION_PRIVATE,
)


@dataclass(frozen=True)
class LocalCommandEvent:
    """本地驱动器内部使用的规整命令事件。"""

    event_id: str
    user_id: str
    raw_message: str
    sender_name: str = ""
    conversation_type: str = CONVERSATION_PRIVATE

    def __post_init__(self) -> None:
        conversation_type = str(self.conversation_type or "").strip().lower()
        if conversation_type not in {CONVERSATION_PRIVATE, CONVERSATION_GROUP}:
            raise ValueError(f"未知本地会话类型：{self.conversation_type}")
        event_id = str(self.event_id or "").strip() or f"local-{uuid4().hex}"
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "user_id", str(self.user_id or "").strip())
        object.__setattr__(self, "raw_message", str(self.raw_message or "").strip())
        object.__setattr__(self, "sender_name", " ".join(str(self.sender_name or "").split()))
        object.__setattr__(self, "conversation_type", conversation_type)


def local_command_event(
    *,
    user_id: str,
    raw_message: str,
    sender_name: str = "",
    conversation_type: str = CONVERSATION_PRIVATE,
    event_id: str = "",
) -> LocalCommandEvent:
    """构造本地命令事件；未传 event_id 时由驱动器生成。"""

    return LocalCommandEvent(
        event_id=event_id or f"local-{uuid4().hex}",
        user_id=user_id,
        raw_message=raw_message,
        sender_name=sender_name,
        conversation_type=conversation_type,
    )
