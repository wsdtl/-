"""纳戒浏览与物品使用命令。"""

from __future__ import annotations

from launch.adapter import MessageContext, MessageHandler

from . import service


@MessageHandler.handler(cmd="纳戒", priority=100, block=True)
async def inventory(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.show_inventory(message, message_context, client_id, manager)


@MessageHandler.handler(cmd="使用物品", priority=100, block=True)
async def use_item(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.use_item(message, message_context, client_id, manager)


__all__ = []
