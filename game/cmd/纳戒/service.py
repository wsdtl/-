"""纳戒分类、50条分页和丹药使用展示。"""

from __future__ import annotations

import asyncio

from game.app import current_game_services
from message import M


async def show_inventory(message: str, context, client_id: str, manager) -> None:
    services = current_game_services()
    user_id = _user_id(context)
    await asyncio.to_thread(services.player.ensure, user_id, context.sender_name)
    parts = str(message or "").split()
    if not parts:
        categories = await asyncio.to_thread(services.player.inventory_categories, user_id)
        reply = M.document().section("纳戒", icon="inventory")
        for key, name, count in categories:
            reply.line(M.command(name, f"纳戒 {name} 1"), f" · {count}类")
        await manager.send(reply.build(), client_id)
        return

    category = _category_id(parts[0], services)
    if category is None:
        await manager.send(_error("未知纳戒类别，请使用：纳戒"), client_id)
        return
    try:
        page = int(parts[1]) if len(parts) > 1 else 1
    except ValueError:
        await manager.send(_error(f"用法：纳戒 {parts[0]} 页码"), client_id)
        return
    if len(parts) > 2:
        await manager.send(_error(f"用法：纳戒 {parts[0]} 页码"), client_id)
        return
    result = await asyncio.to_thread(services.player.inventory_page, user_id, category, page)
    reply = (
        M.document()
        .section(result.category_name, icon="inventory")
        .row(("数量", result.total), ("页码", f"{result.page}/{result.pages}"))
    )
    if not result.entries:
        reply.line("此类物品为空。")
    for index, entry in enumerate(result.entries, start=(result.page - 1) * 50 + 1):
        if result.category == "功法":
            name = M.command(entry.name, f"功法 {entry.key}")
            detail = f" · 评分{entry.score}"
            if entry.equipped_slot is not None:
                detail += f" · 已装配{entry.equipped_slot}位"
            reply.item(index, name, detail)
        else:
            definition = services.content.item_definitions[entry.key]
            if isinstance(definition.get("使用效果"), dict):
                name = M.command(entry.name, f"使用物品 {entry.name}")
            else:
                name = entry.name
            reply.item(index, name, f" ×{entry.quantity} · 评分{entry.score}")
    if result.pages > 1:
        if result.page > 1:
            reply.line(M.command("上一页", f"纳戒 {result.category_name} {result.page - 1}"))
        if result.page < result.pages:
            reply.line(M.command("下一页", f"纳戒 {result.category_name} {result.page + 1}"))
    reply.line(M.command("返回分类", "纳戒"))
    await manager.send(reply.build(), client_id)


async def use_item(message: str, context, client_id: str, manager) -> None:
    text = str(message or "").strip()
    if not text:
        await manager.send(_error("用法：使用物品 名称 数量"), client_id)
        return
    name, quantity = _item_request(text)
    services = current_game_services()
    user_id = _user_id(context)
    await asyncio.to_thread(services.player.ensure, user_id, context.sender_name)
    result = await asyncio.to_thread(services.player.use_item, user_id, name, quantity)
    if result.status == "used":
        text = f"使用{result.item_name}×{result.quantity}，恢复{_number(result.recovered)}点{result.resource}。"
    else:
        text = {
            "not_found": "纳戒中没有这种物品。",
            "not_usable": f"{result.item_name}当前不能直接使用。",
            "insufficient": f"{result.item_name}数量不足。",
            "already_full": f"{result.item_name}对应的状态已经圆满。",
        }[result.status]
    reply = (
        M.document()
        .section("使用物品", icon="item")
        .line(text)
        .line(M.command("查看状态", "状态"), " | ", M.command("返回纳戒", "纳戒"))
        .build()
    )
    await manager.send(reply, client_id)


def _item_request(text: str) -> tuple[str, int]:
    parts = text.rsplit(maxsplit=1)
    if len(parts) == 2:
        try:
            return parts[0], max(1, int(parts[1]))
        except ValueError:
            pass
    return text, 1


def _category_id(value: str, services) -> str | None:
    return value if value in services.content.item_categories else None


def _user_id(context) -> str:
    return context.identity.primary.external_id


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _error(line: str):
    return M.document().section("命令未完成", icon="notice").line(line).build()


__all__ = ["show_inventory", "use_item"]
