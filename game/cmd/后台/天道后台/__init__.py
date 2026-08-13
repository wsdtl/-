"""天道后台命令与受保护的管理台路由。"""

from __future__ import annotations

from ...command import GameCommand
from . import entry
from . import runtime as runtime
from .site import router


@GameCommand.fullmatch(
    scope="后台",
    cmd="天道后台",
    guard_rule="始终可用",
    hidden=True,
)
async def heavenly_dao_console(*, manager) -> None:
    await entry.show_entry(manager=manager)


__all__ = ["router"]
