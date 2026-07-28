"""天道管理台入口回复。"""

from __future__ import annotations

from launch.paths import public_url
from message import Action, M


async def show_entry(*, client_id: str, manager) -> None:
    url = public_url("game-console")
    reply = (
        M.document()
        .section("天道管理台", icon="system")
        .line(M.link("打开天道管理台", url))
        .action(Action("web_console.open", "打开管理台", url, behavior="link"))
        .build()
    )
    await manager.send(reply, client_id)


__all__ = ["show_entry"]
