"""附近修士查看与交谈命令。"""

from __future__ import annotations

from launch.adapter import MessageContext, MessageHandler

from . import service


@MessageHandler.handler(cmd="修士", priority=100, block=True)
async def nearby_npcs(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.show_npc(message, message_context, client_id, manager)


@MessageHandler.handler(cmd="交谈", priority=100, block=True)
async def talk_to_npc(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.talk(message, message_context, client_id, manager)


__all__ = []

