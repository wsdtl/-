"""即时行路命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.xinglu import (
    TravelConflictError,
    TravelQueryError,
    TravelRequest,
)
from message import M

from ..command import GameCommand, HelpSpec


@GameCommand.command(
    cmd="去",
    guard_rule="自主空闲",
    help=HelpSpec(
        category="行动",
        summary="前往指定地点或坐标并立即抵达",
        usage=("去 地点名", "去 x y"),
        side_effect="立即改变人物位置，不产生行路等待时间",
        order=10,
    ),
)
async def travel(
    *,
    user_id: str,
    message: str,
    message_context,
    manager,
) -> None:
    destination = str(message or "").strip()
    if not destination:
        await manager.send(
            M.document()
            .section("行路", icon="navigation")
            .line("格式：去 地点名，或：去 x y")
            .line(M.command("查看全境地图", "地图"))
            .build()
        )
        return
    try:
        result = await current_game_services().features.xinglu.travel(
            TravelRequest(
                user_id=user_id,
                request_id=message_context.request_id,
                destination=destination,
            )
        )
    except TravelQueryError as exc:
        await manager.send(
            M.document().section("行路", icon="navigation").line(str(exc)).build()
        )
        return
    except TravelConflictError:
        await manager.send(
            M.document()
            .section("行路", icon="notice")
            .line("你的位置刚刚发生变化，本次行路没有覆盖新的落脚处，请重新查看人物。")
            .build()
        )
        return

    plan = result.plan
    destination_view = plan.destination
    reply = (
        M.document()
        .header("抵达 · ", _location_name(destination_view))
        .section(f"行路 · {plan.travel_method}", icon="navigation")
    )
    for line in plan.narrative:
        reply.line(line)
    reply.section("落脚处", icon="map")
    reply.field("地点", _location_name(destination_view))
    reply.row(("区域", destination_view.region), ("地形", destination_view.terrain))
    reply.row(
        ("坐标", f"{destination_view.xy[0]}, {destination_view.xy[1]}"),
        ("海拔", f"{destination_view.altitude}米"),
    )
    reply.section("可用功能", icon="guide")
    if destination_view.available_functions:
        for index, function in enumerate(destination_view.available_functions, start=1):
            reply.item(index, function)
    else:
        reply.line("此处没有已经开放的地点功能。")
    await manager.send(reply.build())


def _location_name(location) -> str:
    if location.location_name:
        return location.location_name
    return f"{location.region}·{location.terrain}（{location.xy[0]}, {location.xy[1]}）"


__all__ = []
