"""天道管理台二级组件命令与 HTTP 路由。"""

from __future__ import annotations

from ..command import GameCommand
from . import entry
from . import runtime as runtime
from .site import router


@GameCommand.fullmatch(
    cmd="web",
    guard_rule="始终可用",
    hidden=True,
)
async def web_console(*, manager) -> None:
    await entry.show_entry(manager=manager)


__all__ = ["router"]
