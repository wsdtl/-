"""地点查看与人物移动命令。"""

from __future__ import annotations

from launch.adapter import MessageContext, MessageHandler

from . import service


@MessageHandler.handler(cmd="地图", priority=100, block=True)
async def world_map(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.show_map(message, message_context, client_id, manager)


@MessageHandler.handler(cmd="地点", priority=100, block=True)
async def location_detail(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.show_location(message, message_context, client_id, manager)


@MessageHandler.handler(cmd="前往", priority=100, block=True)
async def move_to_location(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.move(message, message_context, client_id, manager)


__all__ = []
