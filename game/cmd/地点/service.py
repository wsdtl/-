"""地点命令的参数整理与玩家回复。"""

from __future__ import annotations

import asyncio

from game.app import current_game_services
from game.features.didian import (
    ACTIVITY_ACTIVE,
    ALREADY_THERE,
    MOVED,
    NOT_FOUND,
)
from message import M


async def show_map(message: str, context, client_id: str, manager) -> None:
    if str(message or "").strip():
        await manager.send(_error("用法：地图"), client_id)
        return
    services = current_game_services()
    current = await asyncio.to_thread(
        services.location.current,
        _user_id(context),
        context.sender_name,
    )
    (minimum_x, maximum_x), (minimum_y, maximum_y) = services.location.coordinate_bounds
    reply = (
        M.document()
        .section(services.location.world_name, icon="map")
        .line(services.location.world_description)
        .row(("当前地点", current.name), ("坐标", current.coordinate_text))
        .field("坐标边界", f"横轴 {minimum_x}至{maximum_x} · 纵轴 {minimum_y}至{maximum_y}")
        .section("山境一览", icon="world")
    )
    for location in services.location.all_locations():
        distance = services.location.distance(current, location)
        if location.location_id == current.location_id:
            reply.line(location.name, " · ", location.coordinate_text, " · ", location.kind, " · 当前所在")
        else:
            reply.line(
                M.command(location.name, f"地点 {location.name}"),
                " · ",
                location.coordinate_text,
                " · ",
                location.kind,
                " · 距离",
                f"{distance}格",
            )
    reply.line(M.command("查看当前地点", "地点"))
    await manager.send(reply.build(), client_id)


async def show_location(message: str, context, client_id: str, manager) -> None:
    services = current_game_services()
    current = await asyncio.to_thread(
        services.location.current,
        _user_id(context),
        context.sender_name,
    )
    name = " ".join(str(message or "").split())
    target = current if not name else services.location.state_by_name(name)
    if target is None:
        await manager.send(
            M.document()
            .section("地点", icon="notice")
            .line("没有找到名为“", name, "”的地点。")
            .line(M.command("查看地图", "地图"))
            .build(),
            client_id,
        )
        return

    distance = services.location.distance(current, target)
    reply = (
        M.document()
        .section(target.name, icon="navigation")
        .row(("坐标", target.coordinate_text), ("地貌", target.kind))
        .row(
            ("可行之事", _functions(target.functions)),
            ("距当前位置", "当前所在" if distance == 0 else f"{distance}格"),
        )
        .line(target.description)
    )
    if target.location_id == current.location_id:
        _append_function_commands(reply, target.functions)
        _append_npc_commands(reply, target.npcs)
        if target.enemies:
            reply.field("可能遭遇", "、".join(target.enemies))
    else:
        if target.npcs:
            reply.field("常见修士", "、".join(target.npcs))
        if target.enemies:
            reply.field("可能遭遇", "、".join(target.enemies))
        reply.line(M.command(f"前往{target.name}", f"前往 {target.name}"))
    reply.line(M.command("返回地图", "地图"))
    await manager.send(reply.build(), client_id)


async def move(message: str, context, client_id: str, manager) -> None:
    services = current_game_services()
    destination = " ".join(str(message or "").split())
    if not destination:
        current = await asyncio.to_thread(
            services.location.current,
            _user_id(context),
            context.sender_name,
        )
        reply = (
            M.document()
            .section("前往", icon="navigation")
            .row(("当前位置", current.name), ("坐标", current.coordinate_text))
        )
        destinations = sorted(
            (
                (services.location.distance(current, location), location)
                for location in services.location.all_locations()
                if location.location_id != current.location_id
            ),
            key=lambda value: (value[0], value[1].name),
        )
        for distance, location in destinations:
            reply.line(
                M.command(location.name, f"前往 {location.name}"),
                " · ",
                location.coordinate_text,
                " · 距离",
                f"{distance}格",
            )
        reply.line(M.command("查看地图", "地图"))
        await manager.send(reply.build(), client_id)
        return

    result = await asyncio.to_thread(
        services.location.move,
        _user_id(context),
        destination,
        context.sender_name,
    )
    if result.status == MOVED:
        reply = (
            M.document()
            .section("行路", icon="navigation")
            .line("已从", result.previous.name, "行至", result.current.name, "。")
            .line(result.current.description)
            .row(("坐标", result.current.coordinate_text), ("移动距离", f"{result.distance}格"))
            .row(("地貌", result.current.kind), ("可行之事", _functions(result.current.functions)))
        )
        _append_function_commands(reply, result.current.functions)
        _append_npc_commands(reply, result.current.npcs)
        if result.current.enemies:
            reply.field("可能遭遇", "、".join(result.current.enemies))
        reply.line(M.command("查看地点", "地点"), " | ", M.command("返回地图", "地图"))
    elif result.status == ALREADY_THERE:
        reply = (
            M.document()
            .section("行路", icon="navigation")
            .line("你已经在", result.current.label, "。")
            .line(M.command("查看地点", "地点"), " | ", M.command("返回地图", "地图"))
        )
    elif result.status == NOT_FOUND:
        reply = (
            M.document()
            .section("行路", icon="notice")
            .line("没有找到名为“", destination, "”的地点。")
            .line(M.command("查看地图", "地图"))
        )
    elif result.status == ACTIVITY_ACTIVE:
        reply = (
            M.document()
            .section("行路", icon="notice")
            .line("当前位于", result.current.label, "，正在闭关或探险，不能移动。")
            .line(M.command("查看进度", "帮助"))
        )
    else:
        raise RuntimeError(f"未知移动结果：{result.status}")
    await manager.send(reply.build(), client_id)


def _append_function_commands(reply, functions: tuple[str, ...]) -> None:
    parts = []
    for index, name in enumerate(functions):
        if index:
            parts.append(" | ")
        parts.append(M.command(name, name))
    if parts:
        reply.line(*parts)


def _append_npc_commands(reply, npcs: tuple[str, ...]) -> None:
    if not npcs:
        return
    parts = []
    for index, name in enumerate(npcs):
        if index:
            parts.append(" | ")
        parts.append(M.command(name, f"修士 {name}"))
    reply.line(*parts)


def _functions(functions: tuple[str, ...]) -> str:
    return "、".join(functions) if functions else "无"


def _user_id(context) -> str:
    return context.identity.primary.external_id


def _error(line: str):
    return M.document().section("命令未完成", icon="notice").line(line).build()


__all__ = ["move", "show_location", "show_map"]
