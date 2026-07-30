"""人物类命令的读取与展示。"""

from __future__ import annotations

import asyncio

from game.app import current_game_services
from message import M


async def show_status(message: str, context, client_id: str, manager) -> None:
    if str(message or "").strip():
        await manager.send(_error("用法：状态"), client_id)
        return
    services = current_game_services()
    user_id = _user_id(context)
    await asyncio.to_thread(services.player.ensure, user_id, context.sender_name)
    assets, location, seclusion, exploration, partners = await asyncio.gather(
        asyncio.to_thread(services.player.load, user_id),
        asyncio.to_thread(services.location.current, user_id, context.sender_name),
        asyncio.to_thread(services.seclusion.progress, user_id),
        asyncio.to_thread(services.exploration.progress, user_id),
        asyncio.to_thread(services.npc.party_assets, user_id),
    )
    player = assets.player
    if player.breakthrough_pending:
        progress = "待突破"
    else:
        progress = f"{player.experience}/{services.player.experience_required(player.level)}"
    if seclusion is not None:
        activity = f"闭关中 · {seclusion.completed_rounds}/{seclusion.maximum_rounds}轮"
    elif exploration is not None:
        activity = f"探险中 · {exploration.completed_rounds}/{exploration.planned_rounds}轮"
    else:
        activity = "空闲"
    reply = (
        M.document()
        .section(player.name, icon="player")
        .row(("境界", f"Lv{player.level}"), ("修为", progress), ("灵石", player.spirit_stones))
        .row(
            ("血气", _resource(player.health, player.resource_maximum("血气"))),
            ("精神", _resource(player.spirit, player.resource_maximum("精神"))),
            ("体力", _resource(player.stamina, player.resource_maximum("体力"))),
        )
        .row(("当前地点", location.label), ("当前状态", activity))
        .row(("自动用药", "开启" if player.auto_medicine else "关闭"))
    )
    if partners:
        reply.field(
            "同行道侣",
            "、".join(
                f"{value.npc_id} Lv{value.level} · {value.direction_id}"
                for value in partners
            ),
        )
    else:
        reply.field("同行道侣", "无")
    reply = (
        reply.line(
            M.command("地点", "地点"),
            " | ",
            M.command("地图", "地图"),
            " | ",
            M.command("本命武器", "本命武器"),
            " | ",
            M.command("功法", "功法"),
            " | ",
            M.command("纳戒", "纳戒"),
        )
        .build()
    )
    await manager.send(reply, client_id)


async def show_weapon(message: str, context, client_id: str, manager) -> None:
    if str(message or "").strip():
        await manager.send(_error("用法：本命武器"), client_id)
        return
    services = current_game_services()
    assets = await asyncio.to_thread(
        _ensure_and_load,
        services,
        _user_id(context),
        context.sender_name,
    )
    weapon = assets.weapon
    rules = services.content.player["本命武器"]
    reply = (
        M.document()
        .section(weapon.name, icon="weapon")
        .row(
            ("等级", f"Lv{weapon.level}"),
            ("经验", f"{weapon.experience}/{services.player.weapon_experience_required(weapon.level)}"),
            ("攻击", _number(services.player.weapon_attack(weapon))),
        )
        .row(
            ("附魔", f"{len(weapon.enchantments)}/{rules['附魔位']}"),
            ("宝石", f"{len(weapon.gems)}/{rules['宝石位']}"),
        )
        .line("本命武器随探险战果获得经验。")
        .line(M.command("开始探险", "探险"), " | ", M.command("查看状态", "状态"))
        .build()
    )
    await manager.send(reply, client_id)


async def set_auto_medicine(message: str, context, client_id: str, manager) -> None:
    value = str(message or "").strip()
    services = current_game_services()
    user_id = _user_id(context)
    await asyncio.to_thread(services.player.ensure, user_id, context.sender_name)
    if not value:
        player = await asyncio.to_thread(services.player.load, user_id)
        enabled = player.player.auto_medicine
    elif value in {"开", "开启"}:
        player = await asyncio.to_thread(services.player.set_auto_medicine, user_id, True)
        enabled = player.auto_medicine
    elif value in {"关", "关闭"}:
        player = await asyncio.to_thread(services.player.set_auto_medicine, user_id, False)
        enabled = player.auto_medicine
    else:
        await manager.send(_error("用法：自动用药 开 或 自动用药 关"), client_id)
        return
    reply = (
        M.document()
        .section("自动用药", icon="recovery")
        .line("当前：", "开启" if enabled else "关闭")
        .line("开启后，探险战斗中资源低于30%时会连续使用对应丹药。")
        .line(
            M.command("开启", "自动用药 开"),
            " | ",
            M.command("关闭", "自动用药 关"),
        )
        .build()
    )
    await manager.send(reply, client_id)


def _user_id(context) -> str:
    return context.identity.primary.external_id


def _resource(value: float, maximum: float) -> str:
    return f"{_number(value)}/{_number(maximum)}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _error(line: str):
    return M.document().section("命令未完成", icon="notice").line(line).build()


__all__ = ["set_auto_medicine", "show_status", "show_weapon"]
