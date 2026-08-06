"""天道管理台二级组件命令与 HTTP 路由。"""

from __future__ import annotations

from ..command import GameCommand
from . import entry
from . import runtime as runtime
from .site import router


@GameCommand.fullmatch(
    cmd="web",
    access="public",
    activity_rule=None,
    hidden=True,
)
async def web_console(*, client_id: str, manager) -> None:
    await entry.show_entry(client_id=client_id, manager=manager)


__all__ = ["router"]
