"""闭关二级组件命令与守卫触发。"""

from __future__ import annotations

from launch.adapter import MessageContext, MessageHandler, register_command_guard

from . import service


@MessageHandler.handler(cmd="闭关", priority=100, block=True)
async def start_seclusion(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.start(
        message,
        user_id=message_context.identity.primary.external_id,
        display_name=message_context.sender_name,
        client_id=client_id,
        manager=manager,
    )


@MessageHandler.handler(cmd="出关", priority=100, block=True)
async def end_seclusion(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.end(
        message,
        user_id=message_context.identity.primary.external_id,
        client_id=client_id,
        manager=manager,
    )


register_command_guard("game.seclusion", service.guard, priority=200)


__all__ = []
