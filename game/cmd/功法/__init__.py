"""功法查看、装配与卸下命令。"""

from __future__ import annotations

from launch.adapter import MessageContext, MessageHandler

from . import service


@MessageHandler.handler(cmd="功法", priority=100, block=True)
async def techniques(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.handle(message, message_context, client_id, manager)


__all__ = []
