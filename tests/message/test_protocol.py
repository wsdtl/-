from __future__ import annotations

import pytest

from message import Action, M, RenderedMessage, render_local_message
from message.renderers.markdown import render_markdown
from message.renderers.plain_text import render_plain_text


def test_standard_reply_has_stable_sections_and_no_italics() -> None:
    message = (
        M.document()
        .header("人物创建完成")
        .inline_section("状态", "已完成")
        .section("人物")
        .row(("姓名", "林远"), ("性别", "男"))
        .field("境界", "灵动")
        .item(1, "小还丹 × 3")
        .note("数据已保存")
        .build()
    )

    markdown = render_markdown(message.document)
    assert markdown == (
        "**人物创建完成**\n"
        "> 状态: 已完成\n"
        "> \n"
        "> 人物\n"
        "> > 姓名: 林远&nbsp;|&nbsp;性别: 男\n"
        "> > 境界: 灵动\n"
        "> > &#91;1&#93; 小还丹 × 3\n"
        "> \n"
        "> 数据已保存"
    )
    assert "_" not in markdown
    assert "*林远*" not in markdown
    assert "*灵动*" not in markdown

    plain = render_plain_text(message.document)
    assert "人物创建完成" in plain
    assert "姓名: 林远 | 性别: 男" in plain
    assert "_" not in plain
    assert ">" not in plain


@pytest.mark.parametrize("value", ["> 手写引用", "---"])
def test_message_text_rejects_raw_markdown_structure(value: str) -> None:
    with pytest.raises(ValueError):
        M.document().section("测试").line(value)


def test_body_content_requires_a_section() -> None:
    with pytest.raises(ValueError, match="必须属于 section"):
        M.document().line("无归属正文")


def test_unknown_icon_fails_during_rendering() -> None:
    message = M.document().section("测试", icon="unknown").build()

    with pytest.raises(ValueError, match="未知消息图标分类"):
        render_markdown(message.document)


def test_action_ids_must_be_unique_within_a_message() -> None:
    action = Action("confirm", "确认", "确认操作")

    with pytest.raises(ValueError, match="action_id 不能重复"):
        M.document().action(action).action(action).build()


def test_local_renderer_freezes_builders_and_preserves_other_values() -> None:
    rendered = render_local_message(M.document().section("状态").line("正常"))

    assert isinstance(rendered, RenderedMessage)
    assert rendered.kind == "markdown"
    assert rendered.content == "> 状态\n> > 正常"
    sentinel = object()
    assert render_local_message(sentinel) is sentinel


def test_markdown_renderer_escapes_inline_style_characters() -> None:
    message = M.document().section("测试").line("真意_*`\\").build()

    assert render_markdown(message.document) == "> 测试\n> > 真意\\_\\*\\`\\\\"
