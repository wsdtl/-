"""所有业务与驱动器共同遵守的消息语义协议。"""

from .builder import DocumentBuilder, M, rich
from .icons import SECTION_ICONS, icon_for, register_icons
from .render import coerce_message, render_local_message
from .schema import (
    Action,
    CommandLink,
    Document,
    DocumentMessage,
    ImageBlock,
    ImageMessage,
    Message,
    RenderedMessage,
)

__all__ = (
    "SECTION_ICONS",
    "Action",
    "CommandLink",
    "Document",
    "DocumentBuilder",
    "DocumentMessage",
    "ImageBlock",
    "ImageMessage",
    "M",
    "Message",
    "RenderedMessage",
    "coerce_message",
    "icon_for",
    "register_icons",
    "render_local_message",
    "rich",
)
