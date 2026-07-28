"""附近修士查看与交谈回复。"""

from __future__ import annotations

import asyncio

from game.app import current_game_services
from message import M


async def show_npc(message: str, context, client_id: str, manager) -> None:
    services = current_game_services()
    user_id = _user_id(context)
    name = " ".join(str(message or "").split())
    if not name:
        nearby = await asyncio.to_thread(services.npc.nearby, user_id)
        reply = M.document().section("附近修士", icon="player")
        if not nearby:
            reply.line("此地暂未见其他修士。")
        for npc in nearby:
            reply.line(
                M.command(npc.npc_id, f"修士 {npc.npc_id}"),
                " · ",
                npc.level_text,
                " · ",
                npc.title,
                " · ",
                npc.stance,
            )
        reply.line(M.command("返回地点", "地点"))
        await manager.send(reply.build(), client_id)
        return

    npc = await asyncio.to_thread(services.npc.nearby_profile, user_id, name)
    if npc is None:
        await manager.send(_error("当前位置没有这名修士。"), client_id)
        return
    reply = (
        M.document()
        .section(npc.npc_id, icon="player")
        .row(("称号", npc.title), ("等级", npc.level_text))
        .row(("立场", npc.stance), ("本命武器", npc.weapon))
        .field("所修功法", "、".join(npc.techniques))
        .line(npc.description)
    )
    if npc.interactive:
        reply.line(M.command("与其交谈", f"交谈 {npc.npc_id}"))
    reply.line(M.command("返回附近修士", "修士"), " | ", M.command("返回地点", "地点"))
    await manager.send(reply.build(), client_id)


async def talk(message: str, context, client_id: str, manager) -> None:
    name = " ".join(str(message or "").split())
    if not name:
        await manager.send(_error("用法：交谈 修士名"), client_id)
        return
    services = current_game_services()
    result = await asyncio.to_thread(services.npc.talk, _user_id(context), name)
    if result is None:
        await manager.send(_error("当前位置无法与这名修士交谈。"), client_id)
        return
    npc, line = result
    reply = (
        M.document()
        .section(npc.npc_id, icon="message")
        .line("“", line, "”")
        .line(M.command("继续交谈", f"交谈 {npc.npc_id}"), " | ", M.command("查看修士", f"修士 {npc.npc_id}"))
    )
    await manager.send(reply.build(), client_id)


def _user_id(context) -> str:
    return context.identity.primary.external_id


def _error(line: str):
    return M.document().section("命令未完成", icon="notice").line(line).build()


__all__ = ["show_npc", "talk"]
