"""角色命令回复构造。"""

from __future__ import annotations

from game.features.chakan_juese import CharacterOverviewResult
from game.features.chuangjian_renwu import CreateCharacterResult
from message import M


def invalid_create_format():
    return (
        M.document()
        .section("创建人物")
        .line("格式：创建人物 姓名 性别（男或女）")
        .build()
    )


def create_error(message: str):
    return M.document().section("创建人物").line(message).build()


def character_exists():
    return (
        M.document()
        .section("创建人物")
        .line("你已经创建过人物，不能重复创建。")
        .build()
    )


def created(result: CreateCharacterResult):
    builder = (
        M.document()
        .header("人物创建完成")
        .section("身份")
        .row(("姓名", result.name), ("性别", result.gender))
        .row(("境界", result.realm_name), ("等级", 1))
        .section("出生地")
        .field("地点", result.location_name)
        .row(("区域", result.region), ("地形", result.terrain))
        .row(
            ("坐标", f"{result.xy[0]}, {result.xy[1]}"),
            ("海拔", f"{result.altitude}米"),
        )
        .section("初始物资")
    )
    for index, (item_name, grade, quantity) in enumerate(result.initial_items, start=1):
        builder.item(index, f"{item_name} {grade} × {quantity}")
    return builder.build()


def overview_error():
    return (
        M.document()
        .section("人物", icon="notice")
        .line("人物状态暂时无法读取，请稍后再试。")
        .build()
    )


def overview(result: CharacterOverviewResult):
    character = result.character
    builder = (
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
        .row(
            ("坐标", f"{result.xy[0]}, {result.xy[1]}"),
            ("海拔", f"{result.altitude}米"),
        )
        .section("当前资源", icon="status")
    )
    _append_pairs(builder, character.resources)
    builder.section("人物属性", icon="skill")
    _append_pairs(builder, character.attributes)
    builder.section("修行", icon="skill").row(
        *(
            (category, f"{equipped}/{total}")
            for category, equipped, total in result.cultivation_usage
        )
    )
    for content in character.equipped_content:
        builder.field(
            f"{content.category}{content.slot}", f"{content.name} · {content.grade}"
        )
    weapon = character.weapon
    builder.section("本命武器", icon="weapon")
    builder.field("名称", weapon.name)
    builder.row(("器阶", weapon.stage), ("等级", weapon.level))
    builder.row(("攻击", _display_number(weapon.attack)), ("经验", weapon.experience))
    builder.field("器律", f"{len(weapon.equipped_laws)}/{weapon.open_law_slots}")
    for law in weapon.equipped_laws:
        builder.item(law.slot, law.name)
    builder.section("随身物资", icon="inventory").row(
        ("种类", character.inventory.stack_count),
        ("总数", character.inventory.total_quantity),
    )
    builder.field("自动用药", "开启" if character.automatic_medicine else "关闭")
    return builder.build()


def _append_pairs(builder, values: tuple[tuple[str, int | float], ...]) -> None:
    for index in range(0, len(values), 2):
        builder.row(
            *(
                (name, _display_number(value))
                for name, value in values[index : index + 2]
            )
        )


def _display_number(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


__all__ = [
    "character_exists",
    "create_error",
    "created",
    "invalid_create_format",
    "overview",
    "overview_error",
]
