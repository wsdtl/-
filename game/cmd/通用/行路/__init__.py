"""即时行路命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.xinglu import (
    TravelConflictError,
    TravelQueryError,
    TravelRequest,
)

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.command(
    scope="通用",
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
        await manager.send(reply.missing_destination())
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
        await manager.send(reply.query_error(str(exc)))
        return
    except TravelConflictError:
        await manager.send(reply.conflict())
        return
    await manager.send(reply.success(result))


__all__ = []
