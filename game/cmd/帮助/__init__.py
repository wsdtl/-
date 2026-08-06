"""玩家帮助二级组件。"""

from __future__ import annotations

from ..command import GameCommand, HelpSpec
from . import service


@GameCommand.command(
    cmd="帮助",
    access="public",
    activity_rule=None,
    help=HelpSpec(
        category="角色",
        summary="查看当前已经开放的命令分类、写法和影响",
        usage=("帮助", "帮助 分类", "帮助 命令"),
        order=0,
    ),
)
async def help_command(*, message: str, client_id: str, manager) -> None:
    await service.show_help(message, client_id=client_id, manager=manager)


__all__ = []
