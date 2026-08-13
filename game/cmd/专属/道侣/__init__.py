"""道侣查看、交谈、赠礼、邀约和暂别命令。"""

from __future__ import annotations

from decimal import Decimal

from game.app import current_game_services
from game.features.daolv_jiejiao import (
    CompanionAction,
    CompanionFarewellRequest,
    CompanionGiftRequest,
    CompanionInteractionError,
    CompanionInvitationRequest,
    CompanionQueryError,
    CompanionView,
)
from message import Action, M

from ...command import GameCommand, HelpSpec


@GameCommand.command(
    scope="专属",
    cmd="查看道侣",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="查看身边道侣的身份、性情、喜好与当前关系",
        usage=("查看道侣 名称", "查看道侣 编号"),
        side_effect="只读查询，不改变关系或物品",
        order=10,
    ),
)
async def inspect_companion(*, user_id: str, message: str, manager, **_) -> None:
    feature = current_game_services().features.daolv_jiejiao
    query = str(message or "").strip()
    if not query:
        await manager.send(_format_error(feature, _copy(feature, "命令", "查看格式")))
        return
    try:
        view = await feature.inspect(user_id, query)
        await manager.send(_view_message(feature, view))
    except CompanionInteractionError as exc:
        await manager.send(_format_error(feature, str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="交谈",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="与身边的世界道侣交谈",
        usage=("交谈 名称", "交谈 编号"),
        side_effect="只读交谈，不增加好感",
        order=20,
    ),
)
async def converse_companion(*, user_id: str, message: str, manager, **_) -> None:
    feature = current_game_services().features.daolv_jiejiao
    query = str(message or "").strip()
    if not query:
        await manager.send(_format_error(feature, _copy(feature, "命令", "交谈格式")))
        return
    try:
        result = await feature.converse(user_id, query)
        definition = result.view.definition
        reply = (
            M.document()
            .header(_copy(feature, "交谈", "标题", 名称=definition.name))
            .section(definition.title, icon=feature.copy().icons["交谈"])
            .line(f"“{result.line}”")
            .line(definition.dialogue.preference)
            .actions(_actions(feature.actions("交谈", result.view)))
        )
        await manager.send(reply.build())
    except CompanionInteractionError as exc:
        await manager.send(_format_error(feature, str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="赠予",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="向身边道侣赠送其喜欢的灵植",
        usage=(
            "赠予 道侣 灵植",
            "赠予 道侣 灵植 数量",
            "赠予 道侣 灵植 品级 数量",
        ),
        side_effect="消耗灵植并增加好感，首次圆满时发放一次回礼",
        order=30,
    ),
)
async def gift_companion(
    *,
    user_id: str,
    message: str,
    message_context,
    manager,
) -> None:
    feature = current_game_services().features.daolv_jiejiao
    try:
        companion, item, grade, quantity = _gift_arguments(message)
        result = await feature.gift(
            CompanionGiftRequest(
                user_id,
                message_context.request_id,
                companion,
                item,
                grade,
                quantity,
            )
        )
        await manager.send(_gift_message(feature, result))
    except (CompanionInteractionError, ValueError) as exc:
        await manager.send(_format_error(feature, str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="邀约",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="邀约好感圆满的道侣同行",
        usage=("邀约 名称", "邀约 编号"),
        side_effect="占用唯一同行道侣位，首次邀约会固定个人资质与实力波动",
        order=40,
    ),
)
async def invite_companion(
    *, user_id: str, message: str, message_context, manager
) -> None:
    feature = current_game_services().features.daolv_jiejiao
    query = str(message or "").strip()
    if not query:
        await manager.send(_format_error(feature, _copy(feature, "命令", "邀约格式")))
        return
    try:
        result = await feature.invite(
            CompanionInvitationRequest(user_id, message_context.request_id, query)
        )
        definition = result.view.definition
        reply = (
            M.document()
            .header(_copy(feature, "邀约", "标题", 名称=definition.name))
            .section(definition.title, icon=feature.copy().icons["邀约"])
            .line(f"“{result.dialogue}”")
        )
        if result.already_active:
            reply.line(_copy(feature, "邀约", "已经同行", 名称=definition.name))
        elif result.first_invitation:
            reply.line(_copy(feature, "邀约", "首次同行"))
            reply.row(
                ("资质", result.instance.qualification), ("同行", definition.name)
            )
        else:
            reply.line(_copy(feature, "邀约", "再次同行", 名称=definition.name))
        reply.actions(_actions(feature.actions("邀约", result.view)))
        await manager.send(reply.build())
    except (CompanionInteractionError, ValueError) as exc:
        await manager.send(_format_error(feature, str(exc)))


@GameCommand.command(
    scope="专属",
    cmd="暂别",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="道侣",
        summary="让当前同行道侣返回其原本所在地",
        usage=("暂别 名称", "暂别 编号"),
        side_effect="清除同行位，保留好感、赠礼历史与个人实例",
        order=50,
    ),
)
async def farewell_companion(
    *, user_id: str, message: str, message_context, manager
) -> None:
    feature = current_game_services().features.daolv_jiejiao
    query = str(message or "").strip()
    if not query:
        await manager.send(_format_error(feature, _copy(feature, "命令", "暂别格式")))
        return
    try:
        result = await feature.farewell(
            CompanionFarewellRequest(user_id, message_context.request_id, query)
        )
        definition = result.definition
        reply = (
            M.document()
            .header(_copy(feature, "暂别", "标题", 名称=definition.name))
            .section(definition.title, icon=feature.copy().icons["暂别"])
            .line(f"“{result.dialogue}”")
            .line(
                _copy(
                    feature,
                    "暂别",
                    "返回故地",
                    名称=definition.name,
                    地点=definition.location_name,
                )
            )
        )
        reply.actions(_actions(feature.farewell_actions(definition.companion_id)))
        await manager.send(reply.build())
    except (CompanionInteractionError, ValueError) as exc:
        await manager.send(_format_error(feature, str(exc)))


def _view_message(feature, view: CompanionView):
    definition = view.definition
    copy = feature.copy()
    relation_text = (
        _copy(feature, "查看", "尚未结交")
        if view.relation.version == 0
        else _affection(view.relation.current_affection)
    )
    active_here = (
        view.active is not None and view.active.companion_id == definition.companion_id
    )
    return (
        M.document()
        .header(_copy(feature, "查看", "标题", 名称=definition.name))
        .section(_copy(feature, "查看", "身份"), icon=copy.icons["身份"])
        .row(
            (_copy(feature, "查看", "称号"), definition.title),
            (_copy(feature, "查看", "性别"), definition.gender),
        )
        .row(
            (_copy(feature, "查看", "境界"), definition.realm_name),
            (_copy(feature, "查看", "等级"), definition.level),
        )
        .line(definition.description)
        .section(_copy(feature, "查看", "性情"), icon=copy.icons["性情"])
        .line(definition.personality)
        .section(_copy(feature, "查看", "喜好"), icon=copy.icons["喜好"])
        .line(
            "、".join(
                name.removeprefix("灵植-") + "灵植"
                for name in definition.favorite_pool_names
            )
        )
        .line(definition.dialogue.preference)
        .section(_copy(feature, "查看", "关系"), icon=copy.icons["关系"])
        .field(_copy(feature, "查看", "当前好感"), relation_text)
        .line(
            _copy(feature, "查看", "同行中")
            if active_here
            else _copy(feature, "查看", "未同行")
        )
        .actions(_actions(feature.actions("查看", view)))
        .build()
    )


def _gift_message(feature, result):
    definition = result.view.definition
    copy = feature.copy()
    reply = M.document().header(_copy(feature, "赠礼", "标题", 名称=definition.name))
    if not result.accepted:
        return (
            reply.section(definition.title, icon=copy.icons["赠礼"])
            .line(
                _copy(
                    feature, "赠礼", "婉拒", 名称=definition.name, 物品=result.item.name
                )
            )
            .line(f"“{result.dialogue}”")
            .line(_copy(feature, "赠礼", "物品未消耗"))
            .actions(_actions(feature.actions("赠礼", result.view)))
            .build()
        )
    assert result.grade is not None
    if result.replayed:
        reply.section(definition.title, icon=copy.icons["赠礼"]).line(
            _copy(feature, "赠礼", "已处理")
        )
    else:
        reply.section(definition.title, icon=copy.icons["赠礼"]).line(
            _copy(
                feature,
                "赠礼",
                "收下",
                名称=definition.name,
                数量=result.quantity,
                品级=result.grade.name,
                物品=result.item.name,
            )
        ).line(f"“{result.dialogue}”").row(
            (_copy(feature, "赠礼", "基础好感"), _affection(result.base_affection)),
            (
                _copy(feature, "赠礼", "品级倍率", 品级=result.grade.name),
                result.grade.ability_multiplier,
            ),
        ).row(
            (_copy(feature, "赠礼", "实际好感"), _affection(result.affection_gain)),
            (
                _copy(feature, "赠礼", "当前好感"),
                f"{_affection(result.affection_before)} → {_affection(result.affection_after)}",
            ),
        )
    if result.first_full:
        reply.line(_copy(feature, "赠礼", "首次圆满")).line(
            f"“{definition.dialogue.full_affection}”"
        )
        assert result.reward_item is not None and result.reward_grade is not None
        reply.field(
            _copy(feature, "赠礼", "获得回礼"),
            f"{result.reward_grade.name}{result.reward_item.name} × {result.reward_quantity}",
        )
    return reply.actions(_actions(feature.actions("赠礼", result.view))).build()


def _gift_arguments(message: str) -> tuple[str, str, str, int]:
    parts = str(message or "").split()
    if len(parts) < 2 or len(parts) > 4:
        raise CompanionQueryError("格式：赠予 道侣 灵植 [品级] [数量]")
    companion, item = parts[:2]
    grade = ""
    quantity = 1
    rest = parts[2:]
    if len(rest) == 1:
        if rest[0].isdecimal():
            quantity = int(rest[0])
        else:
            grade = rest[0]
    elif len(rest) == 2:
        grade = rest[0]
        if not rest[1].isdecimal():
            raise CompanionQueryError("赠礼数量必须是正整数")
        quantity = int(rest[1])
    if quantity < 1:
        raise CompanionQueryError("赠礼数量必须是正整数")
    return companion, item, grade, quantity


def _copy(feature, section: str, key: str, **values) -> str:
    return feature.copy().text[section][key].format_map(values)


def _format_error(feature, message: str):
    return (
        M.document()
        .section(_copy(feature, "错误", "标题"), icon=feature.copy().icons["错误"])
        .line(message)
        .build()
    )


def _actions(values: tuple[CompanionAction, ...]) -> tuple[Action, ...]:
    return tuple(
        Action(
            value.action_id,
            value.label,
            value.command,
            behavior=value.behavior,
            style=value.style,
        )
        for value in values
    )


def _affection(value: Decimal) -> str:
    return f"{value:.1f}"


__all__ = []
