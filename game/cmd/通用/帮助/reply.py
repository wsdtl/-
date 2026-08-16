"""从命令注册表生成协议中立的帮助消息。"""

from __future__ import annotations

from game.cmd.help_registry import CommandHelpEntry, help_registry
from message import Action, DocumentMessage, M

GAME_NAME = "晓楠修仙"


def help_message(query: str = "") -> DocumentMessage:
    normalized = " ".join(str(query or "").split())
    if not normalized:
        return _home_message()
    elif normalized in help_registry.categories():
        return _category_message(normalized)
    elif entry := help_registry.find(normalized):
        return _detail_message(entry)
    return _not_found_message(normalized)


def _home_message() -> DocumentMessage:
    builder = (
        M.document()
        .header(GAME_NAME)
        .section("帮助", icon="system")
        .line("按分类查看当前已经开放的命令。")
    )
    categories = help_registry.categories()
    for start in range(0, len(categories), 3):
        parts: list[object] = []
        for index, category in enumerate(categories[start : start + 3]):
            if index:
                parts.append("　")
            parts.append(M.command(category, f"帮助 {category}"))
        builder.line(*parts)
    if not categories:
        builder.line("当前还没有登记公开命令。")
    return builder.build()


def _category_message(category: str) -> DocumentMessage:
    builder = M.document().header(GAME_NAME).section(category, icon="system")
    entries = help_registry.in_category(category)
    for entry in entries:
        builder.line(
            M.command(entry.command, f"帮助 {entry.command}"), " - ", entry.spec.summary
        )
    if not entries:
        builder.line("当前分类还没有开放命令。")
    return builder.actions((_home_action(),)).build()


def _detail_message(entry: CommandHelpEntry) -> DocumentMessage:
    builder = (
        M.document()
        .header(GAME_NAME)
        .section(entry.command, icon="system")
        .line(entry.spec.summary)
        .section("写法")
    )
    for usage in entry.spec.usage:
        builder.line(usage)
    if entry.aliases:
        builder.section("别名").line("、".join(entry.aliases))
    if entry.spec.side_effect:
        builder.section("影响").line(entry.spec.side_effect)
    return builder.actions(
        (
            Action("help.execute", "发送命令", entry.command, behavior="callback"),
            Action(
                "help.category",
                "返回分类",
                f"帮助 {entry.spec.category}",
                behavior="callback",
                style="secondary",
            ),
        )
    ).build()


def _not_found_message(query: str) -> DocumentMessage:
    builder = (
        M.document()
        .header(GAME_NAME)
        .section("没有找到帮助", icon="notice")
        .line(f"未登记分类或命令：{query}")
        .section("可用分类")
    )
    for category in help_registry.categories():
        builder.line(M.command(category, f"帮助 {category}"))
    return builder.actions((_home_action(),)).build()


def _home_action() -> Action:
    return Action(
        "help.home", "帮助首页", "帮助", behavior="callback", style="secondary"
    )


__all__ = [
    "_category_message",
    "_detail_message",
    "_home_message",
    "help_message",
]
