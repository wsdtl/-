"""玩家托管命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.tuoguan import HostingFeatureError

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.fullmatch(
    scope="通用",
    cmd="托管",
    guard_rule="可开启托管",
    help=HelpSpec(
        category="行动",
        summary="让本地自动化接管本人或当前同行",
        usage=("托管",),
        side_effect="单人直接托管；队长或宗主会统一托管当前同行成员",
        order=42,
    ),
)
async def start_hosting(*, user_id: str, message_context, manager) -> None:
    feature = current_game_services().features.tuoguan
    try:
        value = await feature.start(user_id, message_context.request_id)
        await manager.send(reply.result(feature.copy(), value))
    except HostingFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


@GameCommand.fullmatch(
    scope="通用",
    cmd="取消托管",
    guard_rule="可取消托管",
    help=HelpSpec(
        category="行动",
        summary="结束本人或当前同行的托管",
        usage=("取消托管",),
        side_effect="单人恢复自主；领队会统一取消当前托管会话",
        order=43,
    ),
)
async def cancel_hosting(*, user_id: str, message_context, manager) -> None:
    feature = current_game_services().features.tuoguan
    try:
        value = await feature.cancel(user_id, message_context.request_id)
        await manager.send(reply.result(feature.copy(), value))
    except HostingFeatureError as exc:
        await manager.send(reply.error(feature.copy(), exc.code))


__all__ = []
