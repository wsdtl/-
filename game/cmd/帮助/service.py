"""帮助命令统一展示当前业务状态和可用入口。"""

from __future__ import annotations

import asyncio

from game.app import current_game_services
from message import M


async def show_help(message: str, *, user_id: str, client_id: str, manager) -> None:
    if str(message or "").strip():
        await manager.send(_message("命令未完成", "用法：帮助"), client_id)
        return

    services = current_game_services()
    seclusion, exploration, partners = await asyncio.gather(
        asyncio.to_thread(services.seclusion.progress, user_id),
        asyncio.to_thread(services.exploration.progress, user_id),
        asyncio.to_thread(services.npc.party, user_id),
    )
    if seclusion is not None:
        location = await asyncio.to_thread(services.location.current, user_id)
        reply = (
            M.document()
            .section("帮助", icon="help")
            .line("当前状态：闭关中")
            .field("当前地点", location.label)
            .row(
                ("已完成感悟", f"{seclusion.completed_rounds}/{seclusion.maximum_rounds}轮"),
                ("结算状态", "可出关" if seclusion.ready else "进行中"),
            )
        )
        if partners:
            reply.field("同行闭关", "、".join(value.npc_id for value in partners))
        reply.line(M.command("刷新进度", "帮助"), " | ", M.command("出关", "出关"))
        reply = reply.build()
    elif exploration is not None:
        location = await asyncio.to_thread(services.location.current, user_id)
        reply = (
            M.document()
            .section("帮助", icon="help")
            .line("当前状态：探险中")
            .field("当前地点", location.label)
            .row(
                ("已完成遭遇", f"{exploration.completed_rounds}/{exploration.planned_rounds}轮"),
                ("结算状态", "可结算" if exploration.ready else "进行中"),
            )
        )
        if exploration.partners:
            reply.field("同行参战", "、".join(exploration.partners))
        reply.line(
            M.command("刷新进度", "帮助"),
            " | ",
            M.command("结束探险", "结束探险"),
        )
        reply = reply.build()
    else:
        reply = (
            M.document()
            .section("修行", icon="help")
            .line(
                M.command("状态", "状态"),
                " | ",
                M.command("闭关", "闭关"),
                " | ",
                M.command("探险", "探险"),
            )
            .section("资产", icon="inventory")
            .line(
                M.command("纳戒", "纳戒"),
                " | ",
                M.command("功法", "功法"),
                " | ",
                M.command("本命武器", "本命武器"),
            )
            .line(
                M.command("使用物品", "使用物品 ", submit=False),
                " | ",
                M.command("自动用药", "自动用药"),
            )
            .section("行路", icon="navigation")
            .line(
                M.command("地图", "地图"),
                " | ",
                M.command("当前地点", "地点"),
                " | ",
                M.command("前往", "前往"),
            )
            .line(
                M.command("附近修士", "修士"),
                " | ",
                M.command("同行伙伴", "伙伴"),
            )
            .section("天道", icon="admin")
            .line(M.command("管理台", "web"))
            .build()
        )
    await manager.send(reply, client_id)


def _message(title: str, line: str):
    return M.document().section(title, icon="notice").line(line).build()


__all__ = ["show_help"]
