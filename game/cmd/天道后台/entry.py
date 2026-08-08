"""天道后台入口回复。"""

from __future__ import annotations

from launch.paths import public_url
from message import Action, M


async def show_entry(*, manager) -> None:
    url = public_url("game-console")
    reply = (
        M.document()
        .section("天道后台", icon="system")
        .line(M.link("打开天道后台", url))
        .action(
            Action(
                "heavenly_dao_console.open",
                "打开后台",
                url,
                behavior="link",
            )
        )
        .build()
    )
    await manager.send(reply)


__all__ = ["show_entry"]
