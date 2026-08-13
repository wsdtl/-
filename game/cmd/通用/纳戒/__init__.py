"""纳戒分类与分页入口。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.najie import (
    NajieCategoryView,
    NajieEntry,
    NajieHome,
    NajiePage,
    NajieQueryError,
    NajieStateError,
)
from message import Action, M

from ...command import GameCommand, HelpSpec


@GameCommand.command(
    scope="通用",
    cmd="纳戒",
    guard_rule="已创建",
    help=HelpSpec(
        category="资源",
        summary="分类查看物品、道藏、器藏、阵藏与所学",
        usage=(
            "纳戒",
            "纳戒 大类",
            "纳戒 大类 小类",
            "纳戒 大类 小类 页码",
        ),
        side_effect="只读查询，不消耗、装配或改变任何玩家资产",
        order=5,
    ),
)
async def show_najie(*, user_id: str, message: str, manager, **_) -> None:
    query = tuple(str(message or "").split())
    feature = current_game_services().features.najie
    try:
        if not query:
            reply = _home_message(await feature.home(user_id))
        elif len(query) == 1:
            reply = _category_message(await feature.category(user_id, query[0]))
        elif len(query) in {2, 3}:
            page = _page_number(query[2]) if len(query) == 3 else 1
            reply = _page_message(await feature.page(user_id, query[0], query[1], page))
        else:
            raise NajieQueryError("纳戒命令最多接收大类、小类和页码")
    except (NajieQueryError, NajieStateError) as exc:
        reply = (
            M.document()
            .section("纳戒", icon="notice")
            .line(str(exc))
            .line("使用“纳戒”返回分类首页。")
            .action(_home_action())
            .build()
        )
    await manager.send(reply)


def _home_message(home: NajieHome):
    builder = M.document().header("晓楠修仙 · 纳戒")
    for category in home.categories:
        builder.section(category.name, icon=category.icon)
        builder.row(("条目", category.entry_count), ("总数", category.total_quantity))
        if category.subcategories:
            for start in range(0, len(category.subcategories), 3):
                parts: list[object] = []
                for index, subcategory in enumerate(
                    category.subcategories[start : start + 3]
                ):
                    if index:
                        parts.append("　")
                    parts.append(
                        M.command(
                            f"{subcategory.name} {subcategory.entry_count}",
                            f"纳戒 {category.name} {subcategory.name}",
                        )
                    )
                builder.line(*parts)
    return builder.build()


def _category_message(view: NajieCategoryView):
    category = view.category
    builder = (
        M.document()
        .header(f"纳戒 · {category.name}")
        .section("总览", icon=category.icon)
        .row(("条目", category.entry_count), ("总数", category.total_quantity))
        .section("分类", icon=category.icon)
    )
    for subcategory in category.subcategories:
        builder.line(
            M.command(
                subcategory.name,
                f"纳戒 {category.name} {subcategory.name}",
            ),
            f" · {subcategory.entry_count}条 / 共{subcategory.total_quantity}份",
        )
    return builder.action(_home_action()).build()


def _page_message(page: NajiePage):
    current_range = f"{page.start_index}-{page.end_index}" if page.entries else "0"
    builder = (
        M.document()
        .header(f"纳戒 · {page.subcategory}")
        .section(f"第{page.page}/{page.total_pages}页", icon=page.icon)
        .row(("条目", page.entry_count), ("总数", page.total_quantity))
        .field("当前", current_range)
        .section("藏中所录", icon=page.icon)
    )
    if not page.entries:
        builder.line("当前小类尚无内容。")
    for index, entry in enumerate(page.entries, start=page.start_index):
        builder.item(index, *_entry_parts(entry))
    actions: list[Action] = []
    if page.page > 1:
        actions.append(
            Action(
                "najie.previous",
                "上一页",
                f"纳戒 {page.category} {page.subcategory} {page.page - 1}",
                behavior="callback",
                style="secondary",
            )
        )
    if page.page < page.total_pages:
        actions.append(
            Action(
                "najie.next",
                "下一页",
                f"纳戒 {page.category} {page.subcategory} {page.page + 1}",
                behavior="callback",
                style="secondary",
            )
        )
    actions.extend(
        (
            Action(
                "najie.category",
                f"返回{page.category}",
                f"纳戒 {page.category}",
                behavior="callback",
                style="secondary",
            ),
            _home_action(),
        )
    )
    return builder.actions(actions).build()


def _entry_parts(entry: NajieEntry) -> tuple[object, ...]:
    name: object = entry.name
    if entry.category == "物品":
        name = M.command(entry.name, f"查看物品 {entry.content_id}")
    parts: list[object] = [name]
    if entry.grade_name:
        parts.extend((" · ", entry.grade_name))
    if entry.category in {"物品", "器藏"} or entry.quantity > 1:
        parts.extend((f" × {entry.quantity}",))
    if entry.equipped_slots:
        parts.extend((" · 已装", "、".join(entry.equipped_slots)))
    if entry.material_total is not None:
        parts.extend((f" · 投入{entry.material_total}份",))
    return tuple(parts)


def _page_number(value: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise NajieQueryError("纳戒页码必须是正整数")
    return int(value)


def _home_action() -> Action:
    return Action(
        "najie.home",
        "返回纳戒",
        "纳戒",
        behavior="callback",
        style="secondary",
    )


__all__ = []
