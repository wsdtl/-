"""公共 Document 到 Markdown 的结构渲染。"""

from __future__ import annotations

from collections.abc import Callable

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

CommandRenderer = Callable[[CommandLink], str]


def render_markdown(
    document: Document, *, command_renderer: CommandRenderer | None = None
) -> str:
    """按统一标题、正文和附加区边界渲染 Markdown。"""

    lines: list[str] = []
    previous_block = None
    for block in document.blocks:
        if isinstance(block, HeaderBlock):
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(_render_header(block, command_renderer))
            previous_block = block
            continue

        should_separate = isinstance(
            previous_block, (InlineBlock, SectionBlock, ImageBlock, NoteBlock)
        ) and not (
            isinstance(previous_block, InlineBlock) and isinstance(block, InlineBlock)
        )
        if should_separate and lines and lines[-1] != "> ":
            lines.append("> ")

        if isinstance(block, InlineBlock):
            title = _title(block.title, block.icon, command_renderer)
            content = _render_rich(block.content, command_renderer)
            lines.append(f"> {title}: {content}".rstrip())
        elif isinstance(block, SectionBlock):
            lines.append(
                f"> {_title(block.title, block.icon, command_renderer)}".rstrip()
            )
            for line in block.lines:
                value = _render_rich(line, command_renderer)
                lines.append("> >" if not value else f"> > {value}")
        elif isinstance(block, ImageBlock):
            size = ""
            if block.width is not None:
                size += f" #{block.width}px"
            if block.height is not None:
                size += f" #{block.height}px"
            lines.append(f"![{_escape(block.alt)}{size}]({_escape_url(block.url)})")
        elif isinstance(block, NoteBlock):
            for line in block.lines:
                value = _render_rich(line, command_renderer)
                lines.append(">" if not value else f"> {value}")
        previous_block = block

    return "\n".join(lines).strip()


def render_rich_markdown(
    value: RichText, *, command_renderer: CommandRenderer | None = None
) -> str:
    """渲染一段 RichText，供协议驱动构造内联能力。"""

    return _render_rich(value, command_renderer)


def _title(value: RichText, icon: str, command_renderer: CommandRenderer | None) -> str:
    title = _render_rich(value, command_renderer)
    display_icon = icon_for(icon)
    return f"{display_icon} {title}".strip()


def _render_rich(value: RichText, command_renderer: CommandRenderer | None) -> str:
    parts: list[str] = []
    for span in value:
        if isinstance(span, Text):
            parts.append(_escape(span.value))
        elif isinstance(span, Link):
            parts.append(
                f"[{_render_rich(span.label, command_renderer)}]({_escape_url(span.url)})"
            )
        elif isinstance(span, CommandLink):
            parts.append(
                command_renderer(span)
                if command_renderer
                else _render_rich(span.label, None)
            )
        elif isinstance(span, FieldSeparator):
            parts.append("&nbsp;|&nbsp;")
    return "".join(parts)


def _render_header(
    block: HeaderBlock,
    command_renderer: CommandRenderer | None,
) -> str:
    if not block.color:
        return f"**{_render_rich(block.content, command_renderer)}**"
    text = "".join(span.value for span in block.content if isinstance(span, Text))
    return f"$\\textcolor{{{block.color}}}{{\\text{{{_escape_latex(text)}}}}}$"


def _escape_latex(value: object) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "%": r"\%",
        "_": r"\_",
        "#": r"\#",
        "&": r"\&",
        "^": r"\^{}",
        "~": r"\~{}",
    }
    return "".join(replacements.get(character, character) for character in str(value))


def _escape(value: object) -> str:
    text = str(value or "")
    for token in ("\\", "`", "*", "_"):
        text = text.replace(token, f"\\{token}")
    text = text.replace("[", "&#91;").replace("]", "&#93;")
    return text.replace("\r", " ").replace("\n", " ")


def _escape_url(value: object) -> str:
    return str(value or "").strip().replace(" ", "%20").replace(")", "%29")
