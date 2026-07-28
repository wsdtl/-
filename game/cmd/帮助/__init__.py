"""帮助二级组件命令触发。"""

from __future__ import annotations

from launch.adapter import MessageContext, MessageHandler

from . import service


@MessageHandler.handler(cmd="帮助", priority=100, block=True)
async def help_command(
    *,
    message: str = "",
    client_id: str,
    message_context: MessageContext,
    manager,
) -> None:
    await service.show_help(
        message,
        user_id=message_context.identity.primary.external_id,
        client_id=client_id,
        manager=manager,
    )


__all__ = []
