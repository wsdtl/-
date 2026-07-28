"""人物状态、本命武器和自动用药命令。"""

from __future__ import annotations

from launch.adapter import MessageContext, MessageHandler

from . import service


@MessageHandler.handler(cmd="状态", priority=100, block=True)
async def player_status(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.show_status(message, message_context, client_id, manager)


@MessageHandler.handler(cmd="本命武器", priority=100, block=True)
async def weapon_status(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.show_weapon(message, message_context, client_id, manager)


@MessageHandler.handler(cmd="自动用药", priority=100, block=True)
async def auto_medicine(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.set_auto_medicine(message, message_context, client_id, manager)


__all__ = []
