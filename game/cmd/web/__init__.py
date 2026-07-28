"""天道管理台二级组件命令与 HTTP 路由。"""

from __future__ import annotations

from launch.adapter import MessageHandler

from . import entry
from . import runtime as runtime
from .site import router


@MessageHandler.handler(cmd="web", priority=100, block=True)
async def web_console(*, client_id: str, manager) -> None:
    await entry.show_entry(client_id=client_id, manager=manager)


__all__ = ["router"]
