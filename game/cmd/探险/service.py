"""探险命令的参数整理与玩家回复。"""

from __future__ import annotations

import asyncio

from game.app import current_game_services
from game.features.tanxian import (
    ALREADY_ACTIVE,
    INSUFFICIENT_STAMINA,
    LOCATION_UNAVAILABLE,
    NO_HEALTH,
    PARTNER_INSUFFICIENT_STAMINA,
    PARTNER_NO_HEALTH,
    SECLUSION_ACTIVE,
    STARTED,
)
from launch.adapter import CommandGuardContext, CommandGuardDecision
from message import M


async def guard(context: CommandGuardContext) -> CommandGuardDecision:
    user_id = context.message_context.identity.primary.external_id
    progress = await asyncio.to_thread(current_game_services().exploration.progress, user_id)
    if progress is None or context.cmd in {"帮助", "结束探险"}:
        return CommandGuardDecision.allow()
    return CommandGuardDecision.block(
        (
            M.document()
            .section("探险中", icon="notice")
            .line("已完成遭遇：", f"{progress.completed_rounds}/{progress.planned_rounds}轮")
            .line(
                "当前只可使用：",
                M.command("帮助", "帮助"),
                " | ",
                M.command("结束探险", "结束探险"),
            )
            .build()
        ),
        reason="exploration_active",
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
        await manager.send(_message("命令未完成", "用法：探险"), client_id)
        return
    result = await asyncio.to_thread(
        current_game_services().exploration.start,
        user_id,
        display_name,
    )
    if result.status == STARTED:
        reply = (
            M.document()
            .section("探险", icon="system")
            .line("已从", result.location_name, "踏入山野，预计可完成", f"{result.planned_rounds}轮遭遇。")
            .line("每满10分钟解锁1轮，结束探险时才会结算战果。")
        )
        if result.partners:
            reply.field("同行参战", "、".join(result.partners))
        reply.line(M.command("查看进度", "帮助"), " | ", M.command("结束探险", "结束探险"))
        reply = reply.build()
    elif result.status == LOCATION_UNAVAILABLE:
        reply = (
            M.document()
            .section("探险", icon="notice")
            .line("当前位于", result.location_name, "，此处不能探险。")
            .line(M.command("查看可去地点", "前往"), " | ", M.command("查看地图", "地图"))
            .build()
        )
    else:
        if result.status == PARTNER_NO_HEALTH:
            reply = _message(
                "探险",
                f"同行伙伴{result.blocked_partner}血气已经耗尽，请先闭关恢复或让其离队。",
            )
            await manager.send(reply, client_id)
            return
        if result.status == PARTNER_INSUFFICIENT_STAMINA:
            reply = _message(
                "探险",
                f"同行伙伴{result.blocked_partner}体力不足10点，请先闭关恢复或让其离队。",
            )
            await manager.send(reply, client_id)
            return
        text = {
            ALREADY_ACTIVE: "当前已经在探险",
            SECLUSION_ACTIVE: "正在闭关，不能开始探险",
            INSUFFICIENT_STAMINA: "体力不足10点，无法开始探险",
            NO_HEALTH: "血气已经耗尽，请先闭关恢复",
        }[result.status]
        reply = _message("探险", text)
    await manager.send(reply, client_id)


async def end(message: str, *, user_id: str, client_id: str, manager) -> None:
    if str(message or "").strip():
        await manager.send(_message("命令未完成", "用法：结束探险"), client_id)
        return
    services = current_game_services()
    result = await asyncio.to_thread(services.exploration.end, user_id)
    if result is None:
        await manager.send(_message("探险", "当前没有探险"), client_id)
        return

    reply = (
        M.document()
        .section("探险结算", icon="system")
        .row(("探险时间", _duration(result.elapsed_seconds)), ("完成遭遇", f"{result.completed_rounds}轮"))
    )
    if result.completed_rounds == 0:
        reply.line("未满10分钟，本次没有完成遭遇，也没有消耗体力。")
    else:
        for encounter in result.encounters:
            label = {"victory": "胜", "defeat": "败", "draw": "未分胜负"}[encounter["result"]]
            reply.item(
                int(encounter["round"]),
                encounter["enemy"],
                " · Lv",
                encounter["enemy_level"],
                " · ",
                label,
            )
        reply.row(("胜利", result.victories), ("未胜", result.defeats))
        reply.row(("灵石", result.spirit_stones), ("本命武器经验", result.weapon_experience))
        if result.weapon_levels_gained:
            reply.field("本命武器提升等级", result.weapon_levels_gained)
        _append_items(reply, "消耗", result.consumed_items, services)
        _append_items(reply, "所得", result.drops, services)
        if result.partners:
            reply.field("同行参战", "、".join(result.partners))
    reply.line(M.command("查看状态", "状态"), " | ", M.command("查看本命武器", "本命武器"))
    await manager.send(reply.build(), client_id)


def _append_items(reply, label: str, values: dict[str, int], services) -> None:
    if not values:
        return
    text = "、".join(
        f"{item_id}×{quantity}"
        for item_id, quantity in sorted(values.items())
    )
    reply.field(label, text)


def _duration(seconds: int) -> str:
    minutes, remainder = divmod(max(0, int(seconds)), 60)
    return f"{minutes}分{remainder}秒" if remainder else f"{minutes}分钟"


def _message(title: str, line: str):
    return M.document().section(title, icon="notice").line(line).build()


__all__ = ["end", "guard", "start"]
