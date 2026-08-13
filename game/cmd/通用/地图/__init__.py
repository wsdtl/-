"""公开地图命令与只读地图页面。"""

from __future__ import annotations

from ...command import GameCommand, HelpSpec
from . import entry
from .site import router


@GameCommand.fullmatch(
    scope="通用",
    cmd="地图",
    guard_rule="始终可用",
    help=HelpSpec(
        category="世界",
        summary="查看晓楠修仙界全境概况与公开舆图",
        usage=("地图",),
        side_effect="只读展示，不改变人物位置或世界状态",
        order=10,
    ),
)
async def show_world_map(*, manager, **_) -> None:
    await entry.show_entry(manager=manager)


__all__ = ["router"]
