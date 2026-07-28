"""QQ 主动发送目标。

业务层的公共 `ReplyTarget` 只描述 adapter/client_id/conversation_type。
QQ 真正发送还需要 actor/user/member openid、group_openid、message_id 等
协议字段，所以这些字段收敛在本模块的 QQ 私有目标里。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..context import CONVERSATION_GROUP, CONVERSATION_PRIVATE, ReplyTarget
from .event import QqMessageEvent


@dataclass(frozen=True)
class QqSendTarget:
    """QQ OpenAPI 发送目标。

    message_id/event_id 为空时就是主动消息；从 QqMessageEvent 构造时会
    保留它们，用于普通被动回复。
    """

    conversation_type: str = CONVERSATION_PRIVATE
    client_id: str = ""
    actor_openid: str = ""
    user_openid: str = ""
    member_openid: str = ""
    group_openid: str = ""
    message_id: str = ""
    event_id: str = ""
    is_wakeup: bool = False

    def __post_init__(self) -> None:
        conversation_type = str(self.conversation_type or "").strip().lower()
        if conversation_type not in {CONVERSATION_PRIVATE, CONVERSATION_GROUP}:
            raise ValueError(f"未知 QQ 会话类型：{self.conversation_type}")
        object.__setattr__(self, "conversation_type", conversation_type)
        object.__setattr__(self, "client_id", str(self.client_id or "").strip())
        object.__setattr__(self, "actor_openid", str(self.actor_openid or "").strip())
        object.__setattr__(self, "user_openid", str(self.user_openid or "").strip())
        object.__setattr__(self, "member_openid", str(self.member_openid or "").strip())
        object.__setattr__(self, "group_openid", str(self.group_openid or "").strip())
        object.__setattr__(self, "message_id", str(self.message_id or "").strip())
        object.__setattr__(self, "event_id", str(self.event_id or "").strip())
        if conversation_type == CONVERSATION_PRIVATE and not str(self.user_openid or "").strip():
            raise ValueError("QQ 私聊发送目标缺少 user_openid")
        if conversation_type == CONVERSATION_GROUP and not str(self.group_openid or "").strip():
            raise ValueError("QQ 群聊发送目标缺少 group_openid")

    @property
    def is_group(self) -> bool:
        """目标是否为群聊。"""

        return self.conversation_type == CONVERSATION_GROUP

    @property
    def is_private(self) -> bool:
        """目标是否为私聊。"""

        return self.conversation_type == CONVERSATION_PRIVATE

    @classmethod
    def from_event(cls, event: QqMessageEvent) -> "QqSendTarget":
        """从入站事件构造带被动回复锚点的发送目标。"""

        return cls(
            conversation_type=CONVERSATION_GROUP if event.is_group else CONVERSATION_PRIVATE,
            client_id=event.client_id,
            actor_openid=event.actor_openid,
            user_openid=event.user_openid,
            member_openid=event.member_openid,
            group_openid=event.group_openid,
            message_id=event.message_id,
            event_id=event.event_id,
        )

    @classmethod
    def private(
        cls,
        user_openid: str,
        *,
        client_id: str = "",
        is_wakeup: bool = False,
    ) -> "QqSendTarget":
        """构造不依赖入站事件的私聊主动发送目标。"""

        openid = str(user_openid or "").strip()
        return cls(
            conversation_type=CONVERSATION_PRIVATE,
            client_id=str(client_id or openid).strip(),
            actor_openid=openid,
            user_openid=openid,
            is_wakeup=bool(is_wakeup),
        )

    @classmethod
    def group(
        cls,
        group_openid: str,
        *,
        client_id: str = "",
        member_openid: str = "",
    ) -> "QqSendTarget":
        """构造不依赖入站事件的群聊主动发送目标。"""

        group_id = str(group_openid or "").strip()
        member_id = str(member_openid or "").strip()
        return cls(
            conversation_type=CONVERSATION_GROUP,
            client_id=str(client_id or member_id or group_id).strip(),
            actor_openid=member_id,
            member_openid=member_id,
            group_openid=group_id,
        )


def qq_private_target(
    user_openid: str,
    *,
    client_id: str = "",
    is_wakeup: bool = False,
) -> ReplyTarget:
    """构造 QQ 私聊主动发送目标。"""

    target = QqSendTarget.private(
        user_openid,
        client_id=client_id,
        is_wakeup=is_wakeup,
    )
    return ReplyTarget(
        adapter="qq",
        client_id=target.client_id,
        conversation_type=CONVERSATION_PRIVATE,
        driver_target=target,
    )


def qq_group_target(
    group_openid: str,
    *,
    client_id: str = "",
    member_openid: str = "",
) -> ReplyTarget:
    """构造 QQ 群聊主动发送目标。"""

    target = QqSendTarget.group(
        group_openid,
        client_id=client_id,
        member_openid=member_openid,
    )
    return ReplyTarget(
        adapter="qq",
        client_id=target.client_id,
        conversation_type=CONVERSATION_GROUP,
        driver_target=target,
    )
