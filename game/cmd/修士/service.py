"""伙伴修士的查看、交谈、送礼与同行回复。"""

from __future__ import annotations

import asyncio

from game.app import current_game_services
from game.features.xiushi import (
    ALREADY_IN_PARTY,
    FAVOR_FULL,
    FAVOR_REQUIRED,
    GIFTED,
    INSUFFICIENT_ITEM,
    INVALID_ITEM,
    INVITED,
    LEFT_PARTY,
    NOT_IN_PARTY,
    NOT_NEARBY,
    NOT_PREFERRED,
)
from message import M


async def show_npc(message: str, context, client_id: str, manager) -> None:
    services = current_game_services()
    user_id = _user_id(context)
    name = " ".join(str(message or "").split())
    if not name:
        nearby = await asyncio.to_thread(
            services.npc.nearby,
            user_id,
            context.sender_name,
        )
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
                "同行中" if npc.in_party else npc.stance,
            )
        reply.line(M.command("同行伙伴", "伙伴"), " | ", M.command("返回地点", "地点"))
        await manager.send(reply.build(), client_id)
        return

    npc = await asyncio.to_thread(
        services.npc.nearby_profile,
        user_id,
        name,
        context.sender_name,
    )
    if npc is None:
        await manager.send(_error("当前位置没有这名修士。"), client_id)
        return
    partner = await asyncio.to_thread(services.npc.partner, user_id, npc.npc_id)
    reply = (
        M.document()
        .section(npc.npc_id, icon="player")
        .row(("称号", npc.title), ("等级", npc.level_text))
        .row(("立场", npc.stance), ("修行方向", "、".join(npc.directions)))
        .row(("好感", npc.favor_text), ("当前", npc.relation_text))
        .field("赠礼偏好", npc.preference_text)
        .line(npc.description)
    )
    if partner is not None:
        _append_partner_asset(reply, partner, include_identity=False)
    _append_relationship_actions(reply, npc)
    reply.line(M.command("返回附近修士", "修士"), " | ", M.command("返回地点", "地点"))
    await manager.send(reply.build(), client_id)


async def show_party(message: str, context, client_id: str, manager) -> None:
    if str(message or "").strip():
        await manager.send(_error("用法：伙伴"), client_id)
        return
    services = current_game_services()
    profiles, assets = await asyncio.gather(
        asyncio.to_thread(
            services.npc.party,
            _user_id(context),
            context.sender_name,
        ),
        asyncio.to_thread(services.npc.party_assets, _user_id(context)),
    )
    party = {value.npc_id: value for value in assets}
    reply = M.document().section("同行伙伴", icon="player")
    if not profiles:
        reply.line("当前没有同行伙伴。")
    for npc in profiles:
        partner = party[npc.npc_id]
        reply.section(npc.npc_id, icon="player").row(
            ("等级", f"Lv{partner.level}"),
            ("方向", partner.direction_id),
            ("资质", partner.aptitude),
        )
        _append_partner_asset(reply, partner, include_identity=False)
        reply.line(M.command("请其离队", f"离队 {npc.npc_id}"))
    reply.line(M.command("查看附近修士", "修士"), " | ", M.command("查看状态", "状态"))
    await manager.send(reply.build(), client_id)


async def talk(message: str, context, client_id: str, manager) -> None:
    name = " ".join(str(message or "").split())
    if not name:
        await manager.send(_error("用法：交谈 修士名"), client_id)
        return
    services = current_game_services()
    result = await asyncio.to_thread(
        services.npc.talk,
        _user_id(context),
        name,
        display_name=context.sender_name,
    )
    if result is None:
        await manager.send(_error("当前位置无法与这名修士交谈。"), client_id)
        return
    npc, line = result
    reply = M.document().section(npc.npc_id, icon="message").line("“", line, "”")
    _append_relationship_actions(reply, npc)
    reply.line(
        M.command("继续交谈", f"交谈 {npc.npc_id}"),
        " | ",
        M.command("查看修士", f"修士 {npc.npc_id}"),
    )
    await manager.send(reply.build(), client_id)


async def gift(message: str, context, client_id: str, manager) -> None:
    parts = str(message or "").split()
    if len(parts) not in {2, 3}:
        await manager.send(_error("用法：送礼 修士名 品级·物品名 [数量]"), client_id)
        return
    quantity = 1
    if len(parts) == 3:
        try:
            quantity = int(parts[2])
        except ValueError:
            quantity = 0
        if quantity < 1:
            await manager.send(_error("赠礼数量必须是正整数。"), client_id)
            return
    services = current_game_services()
    result = await asyncio.to_thread(
        services.npc.gift,
        _user_id(context),
        parts[0],
        parts[1],
        quantity,
        context.sender_name,
    )
    if result.status == GIFTED:
        assert result.profile is not None
        reply = (
            M.document()
            .section("赠礼", icon="inventory")
            .line("已将", _items_text(result.given_items), "赠予", result.profile.npc_id, "。")
            .row(("好感增加", result.favor_gained), ("当前好感", result.profile.favor_text))
        )
        if result.reward_name:
            reply.line(
                result.profile.npc_id,
                "回赠了",
                result.reward_name,
                " ×",
                result.reward_quantity,
                "。",
            )
        _append_relationship_actions(reply, result.profile)
        reply.line(M.command("查看修士", f"修士 {result.profile.npc_id}"))
        await manager.send(reply.build(), client_id)
        return
    errors = {
        INVALID_ITEM: "没有找到这种物品。",
        NOT_PREFERRED: "这件东西不合对方的赠礼偏好，对方没有收下。",
        INSUFFICIENT_ITEM: "纳戒中的对应物品数量不足。",
        FAVOR_FULL: "双方好感已经圆满，不必继续赠礼。",
        NOT_NEARBY: "当前位置没有这名修士。",
    }
    await manager.send(_error(errors[result.status]), client_id)


async def invite(message: str, context, client_id: str, manager) -> None:
    name = " ".join(str(message or "").split())
    if not name:
        await manager.send(_error("用法：邀请入队 修士名"), client_id)
        return
    services = current_game_services()
    result = await asyncio.to_thread(
        services.npc.invite,
        _user_id(context),
        name,
        context.sender_name,
    )
    if result.status == INVITED:
        assert result.profile is not None
        assert result.partner is not None
        reply = (
            M.document()
            .section("伙伴入队", icon="player")
            .line("“", result.line, "”")
            .line(result.profile.npc_id, "已加入队伍，现随你同行。")
        )
        _append_partner_asset(reply, result.partner)
        reply.line(M.command("查看伙伴", "伙伴"), " | ", M.command("继续行路", "前往"))
        reply = reply.build()
    elif result.status == FAVOR_REQUIRED:
        assert result.profile is not None
        reply = _error(f"好感尚未圆满：{result.profile.favor_text}。")
    elif result.status == ALREADY_IN_PARTY:
        reply = _error("这名伙伴已经在队伍中。")
    elif result.status == NOT_NEARBY:
        reply = _error("当前位置没有这名修士。")
    else:
        raise RuntimeError(f"未知邀请结果：{result.status}")
    await manager.send(reply, client_id)


async def leave(message: str, context, client_id: str, manager) -> None:
    name = " ".join(str(message or "").split())
    if not name:
        await manager.send(_error("用法：离队 修士名"), client_id)
        return
    services = current_game_services()
    result = await asyncio.to_thread(
        services.npc.leave,
        _user_id(context),
        name,
        context.sender_name,
    )
    if result.status == LEFT_PARTY:
        assert result.profile is not None
        reply = (
            M.document()
            .section("伙伴离队", icon="player")
            .line("“", result.line, "”")
            .line(result.profile.npc_id, "已离开队伍，返回", result.profile.home_location, "。")
            .line(M.command("查看伙伴", "伙伴"), " | ", M.command("查看地图", "地图"))
            .build()
        )
    elif result.status == NOT_IN_PARTY:
        reply = _error("这名修士不在当前队伍中。")
    else:
        raise RuntimeError(f"未知离队结果：{result.status}")
    await manager.send(reply, client_id)


def _append_relationship_actions(reply, npc) -> None:
    if npc.interactive:
        reply.line(M.command("与其交谈", f"交谈 {npc.npc_id}"))
    if npc.in_party:
        reply.line(M.command("请其离队", f"离队 {npc.npc_id}"))
    elif npc.favor >= npc.favor_max:
        reply.line(M.command("邀请入队", f"邀请入队 {npc.npc_id}"))
    else:
        reply.line(
            M.command(
                "赠送礼物",
                f"送礼 {npc.npc_id} ",
                submit=False,
            )
        )


def _items_text(items) -> str:
    return "、".join(f"{name} ×{quantity}" for name, quantity in items.items())


def _append_partner_asset(reply, partner, *, include_identity: bool = True) -> None:
    if include_identity:
        reply.row(
            ("等级", f"Lv{partner.level}"),
            ("方向", partner.direction_id),
            ("资质", partner.aptitude),
        )
    reply.row(
        (
            "血气",
            _resource(partner.health, partner.resource_maximum("血气")),
        ),
        (
            "精神",
            _resource(partner.spirit, partner.resource_maximum("精神")),
        ),
        (
            "体力",
            _resource(partner.stamina, partner.resource_maximum("体力")),
        ),
    )
    reply.field(
        "本命武器",
        f"{partner.weapon['名称']} · Lv{partner.weapon['等级']}",
    )
    reply.field(f"功法（{len(partner.techniques)}门）", _loadout_text(partner.techniques, "功法"))
    reply.field(f"附魔（{len(partner.enchantments)}个）", _loadout_text(partner.enchantments, "名称"))
    reply.field(f"宝石（{len(partner.gems)}颗）", _loadout_text(partner.gems, "名称"))


def _loadout_text(values, name_key: str) -> str:
    return "、".join(f"{value['品级']}·{value[name_key]}" for value in values) or "无"


def _resource(value: float, maximum: float) -> str:
    return f"{_number(value)}/{_number(maximum)}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _user_id(context) -> str:
    return context.identity.primary.external_id


def _error(line: str):
    return M.document().section("命令未完成", icon="notice").line(line).build()


__all__ = ["gift", "invite", "leave", "show_npc", "show_party", "talk"]
