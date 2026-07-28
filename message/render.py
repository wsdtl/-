"""协议中立消息渲染入口。"""

from __future__ import annotations

from .builder import DocumentBuilder
from .renderers.markdown import render_markdown
from .renderers.plain_text import render_plain_text, render_rich_text
from .schema import DocumentMessage, ImageMessage, Message, RenderedMessage


def coerce_message(value: object) -> Message | None:
    """识别公共消息对象；构造器在发送边界冻结为不可变消息。"""

    if isinstance(value, DocumentBuilder):
        return value.build()
    if isinstance(value, (DocumentMessage, ImageMessage)):
        return value
    return None


def render_local_message(value: object, *, markdown: bool = True) -> object:
    """为本地驱动生成可断言的协议中立结果。"""

    message = coerce_message(value)
    if isinstance(message, DocumentMessage):
        content = render_markdown(message.document) if markdown else render_plain_text(message.document)
        return RenderedMessage(
            kind="markdown" if markdown else "text",
            content=content,
            actions=message.document.actions,
        )
    if isinstance(message, ImageMessage):
        return RenderedMessage(kind="image", content=render_rich_text(message.caption), image=message.image)
    return value
