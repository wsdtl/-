"""查看类命令入口。"""

from __future__ import annotations

from game.app import current_game_services

from ...command import GameCommand, HelpSpec
from . import reply


@GameCommand.command(
    scope="通用",
    cmd="查看物品",
    guard_rule="始终可用",
    help=HelpSpec(
        category="资源",
        summary="按编号或名称查看正式物品定义与功能",
        usage=("查看物品 编号", "查看物品 名称"),
        side_effect="只读查询，不改变人物、背包或世界状态",
        order=10,
    ),
)
async def inspect_item(
    *,
    message: str,
    manager,
    **_,
) -> None:
    query = " ".join(str(message or "").split())
    if not query:
        await manager.send(reply.missing_query())
        return

    result = current_game_services().features.chakan_wupin.inspect(query)
    await manager.send(reply.inspection(result))


__all__ = []
