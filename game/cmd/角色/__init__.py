"""角色二级组件命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.chakan_juese import CharacterOverviewError
from game.features.chuangjian_renwu import (
    CharacterExistsError,
    CreateCharacterRequest,
    InvalidCreateCharacterError,
)
from message import M

from ..command import GameCommand, HelpSpec


@GameCommand.command(
    cmd="创建人物",
    guard_rule="仅未创建",
    help=HelpSpec(
        category="角色",
        summary="建立当前账号的唯一修士人物",
        usage=("创建人物 姓名 性别",),
        side_effect="每个账号只能创建一个人物",
        order=10,
    ),
)
async def create_character(
    *,
    user_id: str,
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
        )
        return
    name, gender = parts
    request = CreateCharacterRequest(
        user_id=user_id,
        request_id=message_context.request_id,
        name=name,
        gender=gender,
    )
    try:
        result = await current_game_services().features.chuangjian_renwu.create(request)
    except InvalidCreateCharacterError as exc:
        await manager.send(
            M.document().section("创建人物").line(str(exc)).build(),
        )
        return
    except CharacterExistsError:
        await manager.send(
            M.document().section("创建人物").line("你已经创建过人物，不能重复创建。").build(),
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
        .row(("坐标", f"{result.xy[0]}, {result.xy[1]}"), ("海拔", f"{result.altitude}米"))
        .section("初始物资")
    )
    for index, (item_name, grade, quantity) in enumerate(result.initial_items, start=1):
        reply.item(index, f"{item_name} {grade} × {quantity}")
    await manager.send(reply.build())


@GameCommand.fullmatch(
    cmd="人物",
    guard_rule="已创建",
    help=HelpSpec(
        category="角色",
        summary="查看当前人物的修为、状态、位置与已有构筑",
        usage=("人物",),
        side_effect="只读查询，不改变人物状态",
        order=20,
    ),
)
async def show_character(*, user_id: str, manager, **_) -> None:
    """显示当前账号对应的人物总览。"""

    try:
        result = await current_game_services().features.chakan_juese.inspect(user_id)
    except CharacterOverviewError:
        await manager.send(
            M.document()
            .section("人物", icon="notice")
            .line("人物状态暂时无法读取，请稍后再试。")
            .build()
        )
        return

    character = result.character
    reply = (
        M.document()
        .header(character.name)
        .section("身份", icon="status")
        .row(("性别", character.gender), ("身份", character.character_type))
        .row(("境界", character.realm_name), ("等级", character.level))
        .row(("经验", character.experience), ("灵石", character.spirit_stones))
        .section("当前状态", icon="status")
        .row(*result.states)
        .section("所在之地", icon="map")
        .field("地点", result.location_name or "野外")
        .row(("区域", result.region), ("地形", result.terrain))
        .row(("坐标", f"{result.xy[0]}, {result.xy[1]}"), ("海拔", f"{result.altitude}米"))
        .section("当前资源", icon="status")
    )
    _append_pairs(reply, character.resources)
    reply.section("人物属性", icon="skill")
    _append_pairs(reply, character.attributes)

    equipped_counts = {
        category: sum(
            content.category == category for content in character.equipped_content
        )
        for category, _ in character.cultivation_slots
    }
    reply.section("修行", icon="skill").row(
        *(
            (category, f"{equipped_counts[category]}/{total}")
            for category, total in character.cultivation_slots
        )
    )
    for content in character.equipped_content:
        reply.field(
            f"{content.category}{content.slot}",
            f"{content.name} · {content.grade}",
        )

    weapon = character.weapon
    reply.section("本命武器", icon="weapon")
    reply.field("名称", weapon.name)
    reply.row(("器阶", weapon.stage), ("等级", weapon.level))
    reply.row(("攻击", _display_number(weapon.attack)), ("经验", weapon.experience))
    reply.field("器律", f"{len(weapon.equipped_laws)}/{weapon.open_law_slots}")
    for law in weapon.equipped_laws:
        reply.item(law.slot, law.name)

    reply.section("随身物资", icon="inventory").row(
        ("种类", character.inventory.stack_count),
        ("总数", character.inventory.total_quantity),
    )
    reply.field("自动用药", "开启" if character.automatic_medicine else "关闭")
    await manager.send(reply.build())


def _append_pairs(builder, values: tuple[tuple[str, int | float], ...]) -> None:
    for index in range(0, len(values), 2):
        builder.row(
            *((name, _display_number(value)) for name, value in values[index : index + 2])
        )


def _display_number(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


__all__ = []
