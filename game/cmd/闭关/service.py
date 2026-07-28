"""闭关命令的参数整理与玩家回复。"""

from __future__ import annotations

import asyncio

from game.app import current_game_services
from game.features.biguan import (
    ALREADY_ACTIVE,
    EXPLORATION_ACTIVE,
    LOCATION_UNAVAILABLE,
    STARTED,
)
from launch.adapter import CommandGuardContext, CommandGuardDecision
from message import M


async def guard(context: CommandGuardContext) -> CommandGuardDecision:
    user_id = context.message_context.identity.primary.external_id
    progress = await asyncio.to_thread(current_game_services().seclusion.progress, user_id)
    if progress is None or context.cmd in {"帮助", "出关"}:
        return CommandGuardDecision.allow()
    return CommandGuardDecision.block(
        (
            M.document()
            .section("闭关中", icon="notice")
            .line("已完成感悟：", f"{progress.completed_rounds}/{progress.maximum_rounds}轮")
            .line("当前只可使用：", M.command("帮助", "帮助"), " | ", M.command("出关", "出关"))
            .build()
        ),
        reason="seclusion_active",
    )


async def start(
    message: str,
    *,
    user_id: str,
    display_name: str,
    client_id: str,
    manager,
) -> None:
    if str(message or "").strip():
        await manager.send(_message("命令未完成", "用法：闭关"), client_id)
        return
    services = current_game_services()
    result = await asyncio.to_thread(services.seclusion.start, user_id, display_name)
    if result == STARTED:
        reply = (
            M.document()
            .section("闭关", icon="system")
            .line("已开始闭关，本次最多感悟6轮。")
            .line("每满10分钟完成1轮，60分钟后恢复至圆满状态。")
            .line(M.command("查看进度", "帮助"), " | ", M.command("提前出关", "出关"))
            .build()
        )
    elif result == LOCATION_UNAVAILABLE:
        location = await asyncio.to_thread(services.location.current, user_id, display_name)
        reply = (
            M.document()
            .section("闭关", icon="notice")
            .line("当前位于", location.label, "，此处不能闭关。")
            .line(M.command("查看可去地点", "前往"), " | ", M.command("查看地图", "地图"))
            .build()
        )
    else:
        text = {
            ALREADY_ACTIVE: "当前已经在闭关",
            EXPLORATION_ACTIVE: "正在探险，不能开始闭关",
        }[result]
        reply = _message("闭关", text)
    await manager.send(reply, client_id)


async def end(message: str, *, user_id: str, client_id: str, manager) -> None:
    if str(message or "").strip():
        await manager.send(_message("命令未完成", "用法：出关"), client_id)
        return
    services = current_game_services()
    result = await asyncio.to_thread(services.seclusion.end, user_id)
    if result is None:
        await manager.send(_message("闭关", "当前没有闭关"), client_id)
        return

    reply = (
        M.document()
        .section("出关", icon="system")
        .row(("闭关时间", _duration(result.elapsed_seconds)), ("完成感悟", f"{result.completed_rounds}轮"))
        .row(
            ("恢复血气", _number(result.recovered_health)),
            ("恢复精神", _number(result.recovered_spirit)),
            ("恢复体力", _number(result.recovered_stamina)),
        )
    )
    if result.completed_rounds == 0:
        reply.line("未满10分钟，本次没有感悟奖励。")
    else:
        reply.field("人物经验", result.experience)
        if result.levels_gained:
            reply.field("提升等级", result.levels_gained)
        if result.breakthrough_pending:
            reply.line("修为已至关隘，突破前不再增长等级与经验。")
        for technique in result.techniques:
            reply.line(
                "感悟所得：",
                M.command(
                    f"{technique.rarity_id}·{technique.technique_id}",
                    f"功法 {technique.born_order}",
                ),
            )
        if not result.techniques:
            reply.line("本次没有悟得新功法。")
    reply.line(M.command("查看状态", "状态"), " | ", M.command("查看功法", "功法"))
    await manager.send(reply.build(), client_id)


def _duration(seconds: int) -> str:
    minutes, remainder = divmod(max(0, int(seconds)), 60)
    return f"{minutes}分{remainder}秒" if remainder else f"{minutes}分钟"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _message(title: str, line: str):
    return M.document().section(title, icon="notice").line(line).build()


__all__ = ["end", "guard", "start"]
