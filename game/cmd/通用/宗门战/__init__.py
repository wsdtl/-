"""宗门战命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.zongmen_zhan import SectWarError
from message import M

from ...command import GameCommand, HelpSpec


def _feature():
    return current_game_services().features.zongmen_zhan


@GameCommand.command(scope="通用", cmd="约战", guard_rule="宗门战发起", help=HelpSpec(category="战斗", summary="向另一宗门发起约战", usage=("约战 宗门名 灵石数量",), order=1))
async def challenge(*, user_id, message, message_context, manager, **_) -> None:
    parts = str(message or "").split()
    if len(parts) != 2:
        await manager.send(_error(_feature().text("错误", "格式")))
        return
    try:
        value = await _feature().challenge(user_id, parts[0], int(parts[1]), message_context.request_id)
        await manager.send(_reply(value, _feature()))
    except (SectWarError, ValueError) as exc:
        await manager.send(_error(str(exc)))


@GameCommand.command(scope="通用", cmd="应战", guard_rule="宗门战参战", help=HelpSpec(category="战斗", summary="接受宗门战书", usage=("应战 战书编号",), order=2))
async def accept(*, user_id, message, message_context, manager, **_) -> None:
    await _run(manager, _feature().accept(user_id, str(message).strip(), message_context.request_id))


@GameCommand.command(scope="通用", cmd="锁定宗门战", guard_rule="宗门战参战", help=HelpSpec(category="战斗", summary="锁定宗门同行阵容", usage=("锁定宗门战 战书编号",), order=3))
async def lock(*, user_id, message, message_context, manager, **_) -> None:
    await _run(manager, _feature().lock(user_id, str(message).strip(), message_context.request_id))


@GameCommand.command(scope="通用", cmd="开战", guard_rule="宗门战参战", help=HelpSpec(category="战斗", summary="双方锁定后开始宗门战", usage=("开战 战书编号",), order=4))
async def start(*, user_id, message, message_context, manager, **_) -> None:
    await _run(manager, _feature().start(user_id, str(message).strip(), message_context.request_id))


@GameCommand.command(scope="通用", cmd="宗门战况", guard_rule="已创建", help=HelpSpec(category="战斗", summary="查看宗门战况", usage=("宗门战况 战书编号",), order=5))
async def view(*, message, manager, **_) -> None:
    try:
        feature = _feature()
        await manager.send(_reply(await feature.view(str(message).strip()), feature))
    except (SectWarError, ValueError) as exc:
        await manager.send(_error(str(exc)))


@GameCommand.command(scope="通用", cmd="结算宗门战", guard_rule="宗门战参战", help=HelpSpec(category="战斗", summary="结束后结算宗门战", usage=("结算宗门战 战书编号",), order=6))
async def settle(*, user_id, message, message_context, manager, **_) -> None:
    await _run(manager, _feature().settle(user_id, str(message).strip(), message_context.request_id))


async def _run(manager, operation) -> None:
    try:
        feature = _feature()
        await manager.send(_reply(await operation, feature))
    except (SectWarError, ValueError) as exc:
        await manager.send(_error(str(exc)))


def _reply(value, feature):
    return (
        M.document()
        .header(feature.text("查看", "标题"))
        .section(feature.text("查看", "状态"))
        .field(feature.text("查看", "双方"), feature.text("格式", "双方", 甲=value.attacker_name, 乙=value.defender_name))
        .field(feature.text("查看", "状态"), value.status)
        .field(feature.text("查看", "人数"), feature.text("格式", "人数", 甲=value.attacker_count, 乙=value.defender_count))
        .field(feature.text("查看", "押注"), feature.text("格式", "押注", 数量=value.wager))
        .build()
    )


def _error(value: str):
    return M.document().header("宗门战").line(value).build()


__all__ = []
