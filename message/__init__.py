"""所有业务与驱动器共同遵守的消息语义协议。"""

from .builder import DocumentBuilder as DocumentBuilder
from .builder import M as M
from .builder import rich as rich
from .icons import SECTION_ICONS as SECTION_ICONS
from .icons import icon_for as icon_for
from .icons import register_icons as register_icons
from .render import coerce_message as coerce_message
from .render import render_local_message as render_local_message
from .schema import Action as Action
from .schema import CommandLink as CommandLink
from .schema import Document as Document
from .schema import DocumentMessage as DocumentMessage
from .schema import ImageMessage as ImageMessage
from .schema import ImageBlock as ImageBlock
from .schema import Message as Message
from .schema import RenderedMessage as RenderedMessage
