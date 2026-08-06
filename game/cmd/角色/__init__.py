"""角色二级组件命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.chuangjian_renwu import (
    CharacterExistsError,
    CreateCharacterRequest,
    InvalidCreateCharacterError,
)
from launch.adapter import MessageHandler
from message import M


@MessageHandler.command(cmd="创建人物", priority=100, block=True)
async def create_character(
    *,
    client_id: str,
    message: str,
    message_context,
    manager,
) -> None:
    """创建当前QQ身份唯一对应的玩家人物。"""

    parts = message.split()
    if len(parts) != 2:
        await manager.send(
            M.document()
            .section("创建人物")
            .line("格式：创建人物 姓名 性别（男或女）")
            .build(),
            client_id,
        )
        return
    name, gender = parts
    identity = message_context.identity
    request = CreateCharacterRequest(
        user_id=identity.primary.external_id,
        request_id=identity.evidence_id,
        name=name,
        gender=gender,
    )
    try:
        result = await current_game_services().features.chuangjian_renwu.create(request)
    except InvalidCreateCharacterError as exc:
        await manager.send(
            M.document().section("创建人物").line(str(exc)).build(),
            client_id,
        )
        return
    except CharacterExistsError:
        await manager.send(
            M.document().section("创建人物").line("你已经创建过人物，不能重复创建。").build(),
            client_id,
        )
        return

    reply = (
        M.document()
        .header("人物创建完成")
        .section("身份")
        .row(("姓名", result.name), ("性别", result.gender))
        .row(("境界", result.realm_name), ("等级", 1))
        .section("出生地")
        .field("地点", result.location_name)
        .row(("区域", result.region), ("地形", result.terrain))
        .row(("坐标", f"{result.coordinate[0]}, {result.coordinate[1]}"), ("海拔", f"{result.altitude}米"))
        .section("初始物资")
    )
    for index, (item_name, grade, quantity) in enumerate(result.initial_items, start=1):
        reply.item(index, f"{item_name} {grade} × {quantity}")
    await manager.send(reply.build(), client_id)


__all__ = []
