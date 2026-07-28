"""协议中立的消息上下文与发送意图。

业务层只能依赖本模块公开的身份、会话、能力和目标；QQ event 等协议对象只可
存在于 driver_context/driver_target。常规账号识别使用 MessageIdentity，不需要读取私有事件。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


CONVERSATION_PRIVATE = "private"
CONVERSATION_GROUP = "group"

MENTION_DEFAULT = "default"
MENTION_NONE = "none"
MENTION_SENDER = "sender"


@dataclass(frozen=True)
class AdapterCapabilities:
    """当前驱动器声明给业务层看的能力，不暴露协议私有字段。"""

    text: bool = True
    markdown: bool = False
    image: bool = False
    buttons: bool = False
    mention: bool = False
    private_message: bool = False
    group_message: bool = False
    active_push: bool = False


@dataclass(frozen=True, order=True)
class MessageIdentityClaim:
    """驱动器从已验证事件中提取的一条稳定身份事实。"""

    provider_id: str
    tenant_id: str
    subject_kind: str
    scope_id: str
    external_id: str

    def __post_init__(self) -> None:
        for field_name in ("provider_id", "tenant_id", "subject_kind", "external_id"):
            value = str(getattr(self, field_name) or "").strip()
            if not value:
                raise ValueError(f"MessageIdentityClaim 缺少 {field_name}")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "scope_id", str(self.scope_id or "").strip())

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        return (
            self.provider_id,
            self.tenant_id,
            self.subject_kind,
            self.scope_id,
            self.external_id,
        )


@dataclass(frozen=True)
class MessageIdentity:
    """一条已验证消息证明的主身份与别名集合。"""

    evidence_id: str
    source_kind: str
    primary: MessageIdentityClaim
    aliases: tuple[MessageIdentityClaim, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("evidence_id", "source_kind"):
            value = str(getattr(self, field_name) or "").strip()
            if not value:
                raise ValueError(f"MessageIdentity 缺少 {field_name}")
            object.__setattr__(self, field_name, value)
        claims = (self.primary, *tuple(self.aliases))
        if len({claim.key for claim in claims}) != len(claims):
            raise ValueError("MessageIdentity 存在重复身份事实")
        namespaces = {(claim.provider_id, claim.tenant_id) for claim in claims}
        if len(namespaces) != 1:
            raise ValueError("一条消息身份不能跨平台或跨租户")
        object.__setattr__(self, "aliases", tuple(self.aliases))


@dataclass(frozen=True)
class ReplyTarget:
    """一次回复的目标。

    公共层只识别 adapter / client_id / conversation_type。driver_target
    由具体驱动解释，例如 QQ 会放 QqMessageEvent。
    """

    adapter: str
    client_id: str
    conversation_type: str
    driver_target: Any = None


@dataclass(frozen=True)
class MessageContext:
    """一条已规整消息的公共上下文。"""

    adapter: str
    client_id: str
    command: str
    message: str
    raw_message: str
    conversation_type: str
    reply_target: ReplyTarget
    capabilities: AdapterCapabilities
    identity: MessageIdentity
    driver_context: Any = None
    sender_name: str = ""


@dataclass(frozen=True)
class SendOptions:
    """业务层表达发送意图时可选的通用发送选项。"""

    mention: str = MENTION_DEFAULT
    reply_mode: str = "reply"
    buttons: bool = True
    markdown: bool = True
    image: bool = True
    log: bool = True


@dataclass(frozen=True)
class SendRequest:
    """一次发送请求。message 是业务内容，target 缺省表示当前回复目标。"""

    message: object
    target: ReplyTarget | None = None
    options: SendOptions = field(default_factory=SendOptions)
    request_id: object | None = None


@dataclass(frozen=True)
class SendResult:
    """驱动器发送结果。"""

    success: bool
    adapter: str = ""
    client_id: str = ""
    error: str = ""


_current_message_context: ContextVar[MessageContext | None] = ContextVar(
    "adapter_explicit_message_context",
    default=None,
)


def set_current_message_context(context: MessageContext) -> Token[MessageContext | None]:
    """设置当前消息上下文，并返回可 reset 的 token。"""

    return _current_message_context.set(context)


def reset_current_message_context(token: Token[MessageContext | None]) -> None:
    """恢复上一个消息上下文。"""

    _current_message_context.reset(token)


def current_message_context() -> MessageContext | None:
    """读取当前消息上下文。"""

    return _current_message_context.get()


def current_reply_target() -> ReplyTarget | None:
    """读取当前消息的默认回复目标。"""

    context = current_message_context()
    if context is None:
        return None
    return context.reply_target
