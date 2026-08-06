"""公共 Document 到纯文本的明确降级渲染。"""

from __future__ import annotations

from ..icons import icon_for
from ..schema import (
    CommandLink,
    Document,
    FieldSeparator,
    HeaderBlock,
    ImageBlock,
    InlineBlock,
    Link,
    NoteBlock,
    RichText,
    SectionBlock,
    Text,
)


def render_plain_text(document: Document) -> str:
    lines: list[str] = []
    previous_block = None
    for block in document.blocks:
        if lines and not (
            isinstance(previous_block, InlineBlock) and isinstance(block, InlineBlock)
        ):
            lines.append("")
        if isinstance(block, HeaderBlock):
            lines.append(_render_rich(block.content))
        elif isinstance(block, InlineBlock):
            title = _title(block.title, block.icon)
            lines.append(f"{title}: {_render_rich(block.content)}".rstrip())
        elif isinstance(block, SectionBlock):
            lines.append(_title(block.title, block.icon))
            lines.extend(_render_rich(line) for line in block.lines)
        elif isinstance(block, ImageBlock):
            lines.append(f"[{block.alt}]")
        elif isinstance(block, NoteBlock):
            lines.extend(_render_rich(line) for line in block.lines)
        previous_block = block
    return "\n".join(lines).strip()


def render_rich_text(value: RichText) -> str:
    return _render_rich(value)


def _title(value: RichText, icon: str) -> str:
    return f"{icon_for(icon)} {_render_rich(value)}".strip()


def _render_rich(value: RichText) -> str:
    parts: list[str] = []
    for span in value:
        if isinstance(span, Text):
            parts.append(span.value.replace("\r", " ").replace("\n", " "))
        elif isinstance(span, Link):
            parts.append(f"{_render_rich(span.label)} ({span.url})")
        elif isinstance(span, CommandLink):
            parts.append(_render_rich(span.label))
        elif isinstance(span, FieldSeparator):
            parts.append(" | ")
    return "".join(parts)
