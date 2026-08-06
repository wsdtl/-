"""生成境界、突破丹和突破丹方；游戏运行时不导入本文件。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REALM_OUTPUT = ROOT / "data" / "内容" / "角色" / "境界.json"
PILL_OUTPUT = ROOT / "data" / "内容" / "物品" / "丹药" / "突破丹" / "突破丹-境界.json"
RECIPE_OUTPUT = ROOT / "data" / "内容" / "炼药" / "丹方" / "突破丹" / "丹方-境界.json"

REALMS = (
    ("灵动", 1, 5, "初识灵气，使灵息能够在血肉间往复。"),
    ("炼气", 6, 10, "引气入体，炼散乱灵息为可用真气。"),
    ("开脉", 11, 15, "贯通经脉，使真气能够周流全身。"),
    ("周天", 16, 20, "气行周天，内外循环开始自成一体。"),
    ("筑基", 21, 25, "夯实道基，使往后修行有根可依。"),
    ("灵海", 26, 30, "丹田拓为灵海，真气由流转化为蓄积。"),
    ("神藏", 31, 35, "开启身中神藏，血肉与神识共同蕴灵。"),
    ("灵台", 36, 40, "灵台澄明，神识得以照见内外。"),
    ("紫府", 41, 45, "开辟紫府，使神识拥有安驻之所。"),
    ("金丹", 46, 50, "百脉归丹，一点金性统摄周身真元。"),
    ("元婴", 51, 55, "丹破婴生，性命凝成第二灵胎。"),
    ("婴变", 56, 60, "元婴数变，逐步脱去后天形质。"),
    ("化神", 61, 65, "神与法合，举念之间可调动天地灵机。"),
    ("出窍", 66, 70, "神魂离体而真性不散，可远游天地。"),
    ("分神", 71, 75, "一念化众念，分化神识仍能归于本真。"),
    ("洞玄", 76, 80, "洞见玄关，开始触及天地运转之理。"),
    ("炼虚", 81, 85, "炼神返虚，形神可与虚空相接。"),
    ("合体", 86, 90, "法身、元神与肉身重新合一。"),
    ("大乘", 91, 95, "所修诸法趋于圆融，只待劫数检验。"),
    ("渡劫", 96, 100, "直面天地劫数，于毁灭中淬炼道果。"),
)

PLAIN_NAMES = (
    "聚气丹",
    "通脉丹",
    "周天丹",
    "筑基丹",
    "凝海丹",
    "开藏丹",
    "登台丹",
    "紫府丹",
    "结丹金液",
    "结婴丹",
    "化婴丹",
    "化神丹",
    "出窍丹",
    "分神丹",
    "洞玄丹",
    "炼虚丹",
    "合体丹",
    "大乘丹",
    "渡劫丹",
)

# 五列依次对应血气、精神、攻击、防御和速度。名称逐境界审定，不做境界名直拼。
FOUNDATION_NAMES = (
    ("赤元聚气", "清心引灵", "庚金试锋", "玄甲纳气", "流云入袖"),
    ("赤脉回龙", "玉关照神", "裂石开脉", "镇岳护关", "追风贯脉"),
    ("九转养元", "周天明神", "星枢催锋", "八门固体", "七曜流光"),
    ("地髓培元", "玉液澄心", "道基藏锋", "金阙固本", "青霄履云"),
    ("沧溟生血", "海心蕴神", "怒潮摧岸", "重渊护体", "鲲游万里"),
    ("五藏生元", "神阙养魄", "秘藏出锋", "黄庭镇身", "灵枢移影"),
    ("登台沐血", "明镜照神", "天台问锋", "玉阶守身", "云梯步虚"),
    ("紫炁养元", "紫府凝神", "丹霞砺锋", "紫垣护命", "天游御风"),
    ("金液洗髓", "一粒明心", "丹火炼锋", "混元护体", "金虹遁空"),
    ("婴元返生", "抱婴守神", "元胎孕锋", "灵胎护主", "婴光瞬游"),
    ("蜕婴换血", "九变化神", "灵蜕藏锋", "无垢护胎", "玄蜕移形"),
    ("神血同源", "太一存神", "神锋开天", "法身镇界", "阳神游天"),
    ("返虚养命", "神游定魄", "灵光斩念", "阴神护体", "一念出游"),
    ("千念归元", "分神合意", "万念成锋", "诸念护身", "化念无踪"),
    ("玄门生元", "洞真观神", "玄枢破妄", "玄关镇体", "洞虚步天"),
    ("虚空炼血", "太虚凝神", "虚刃断界", "无相护真", "蹑虚无迹"),
    ("天人养元", "三元归神", "法体合锋", "天人不坏", "六合同尘"),
    ("乘愿生身", "万法归心", "大道藏锋", "金身不灭", "乘光越界"),
    ("劫火铸血", "九霄镇神", "天雷砺锋", "玄穹镇厄", "天门遁影"),
)

REALM_SIGILS = (
    "灵泉",
    "天关",
    "星轮",
    "道台",
    "沧海",
    "黄庭",
    "玉台",
    "紫垣",
    "金炉",
    "灵胎",
    "神蜕",
    "太一",
    "神游",
    "万念",
    "玄门",
    "太虚",
    "天人",
    "大道",
    "九霄",
)

FOUNDATIONS = (
    ("血气上限", "血气上限"),
    ("精神上限", "精神上限"),
    ("攻击", "攻击"),
    ("防御", "防御"),
    ("速度", "速度"),
)

COMPOUNDS = (
    ("照胆", ("暴击率", "暴击伤害")),
    ("玄壁", ("格挡率", "格挡减伤")),
    ("断岳", ("破格率", "比例穿透")),
    ("定魂", ("控制抵抗率", "韧性")),
    ("回炁", ("冷却缩减", "精神消耗修正")),
    ("连星", ("连击率", "连击伤害")),
    ("返锋", ("反击率", "反伤率")),
    ("洞见", ("命中率", "破格率")),
    ("济护", ("治疗加成", "护盾加成")),
)

VALID_ATTRIBUTES = {
    "血气上限",
    "精神上限",
    "攻击",
    "防御",
    "速度",
    "命中率",
    "暴击率",
    "暴击伤害",
    "格挡率",
    "破格率",
    "格挡减伤",
    "比例穿透",
    "治疗加成",
    "护盾加成",
    "控制抵抗率",
    "韧性",
    "冷却缩减",
    "精神消耗修正",
    "反伤率",
    "连击率",
    "连击伤害",
    "反击率",
}

DIFFICULTIES = (1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10)
CHOICE_COUNTS = (7, 7, 7, 7, 9, 9, 9, 9, 9, 9, 11, 11, 11, 11, 11, 11, 13, 13, 15)
FURNACES = {
    1: ("青华逐霞", "水木还生"),
    2: ("金土铸甲", "五炁朝元"),
    3: ("青离合契", "五炁同心"),
    4: ("水木共济", "坤玄守阙"),
    5: ("青坤传炁", "五炁护命"),
    6: ("河洛归真", "紫极炼形"),
    7: ("婴火分光", "三花聚顶"),
    8: ("洞天返虚", "太虚合炁"),
    9: ("天人交泰", "万法归一"),
    10: ("九霄渡厄", "五雷炼真"),
}


def _number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _foundation_bonus(node: int, attribute: str) -> int | float:
    units = node + 1
    if attribute == "血气上限":
        return 6 * units
    if attribute == "精神上限":
        return 3 * units
    if attribute == "攻击":
        return _number(0.4 * units)
    if attribute == "防御":
        return round(0.6 * units)
    return round(0.5 * units)


def _compound_bonus(node: int, attributes: tuple[str, str]) -> dict[str, int]:
    minor = 1 + node // 6
    major = 2 + node // 4
    first, second = attributes
    if attributes in {
        ("暴击率", "暴击伤害"),
        ("格挡率", "格挡减伤"),
        ("连击率", "连击伤害"),
    }:
        return {first: minor, second: major}
    if attributes == ("命中率", "破格率"):
        return {first: major, second: minor}
    if attributes == ("治疗加成", "护盾加成"):
        return {first: major, second: major}
    return {first: minor, second: minor}


def build_realms() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for index, (name, lower, upper, description) in enumerate(REALMS, start=1):
        realm: dict[str, object] = {
            "编号": f"510{index:03d}",
            "名称": name,
            "等级下限": lower,
            "等级上限": upper,
            "说明": description,
        }
        if index < len(REALMS):
            realm["下一境界"] = f"510{index + 1:03d}"
        output.append(realm)
    return output


def build_pills_and_recipes() -> tuple[
    list[dict[str, object]], list[dict[str, object]]
]:
    pills: list[dict[str, object]] = []
    recipes: list[dict[str, object]] = []
    serial = 0
    for target_index, target in enumerate(REALMS[1:], start=1):
        target_name = target[0]
        target_realm_id = f"510{target_index + 1:03d}"
        variants: list[tuple[str, dict[str, int | float] | None]] = [
            (PLAIN_NAMES[target_index - 1], None)
        ]
        for name, (attribute, _label) in zip(
            FOUNDATION_NAMES[target_index - 1], FOUNDATIONS, strict=True
        ):
            variants.append(
                (f"{name}丹", {attribute: _foundation_bonus(target_index, attribute)})
            )

        compound_count = CHOICE_COUNTS[target_index - 1] - 6
        start = ((target_index - 1) * 2) % len(COMPOUNDS)
        for offset in range(compound_count):
            title, attributes = COMPOUNDS[(start + offset) % len(COMPOUNDS)]
            sigil = REALM_SIGILS[target_index - 1]
            name = f"{sigil}{title}丹" if target_index % 2 else f"{title}{sigil}丹"
            variants.append((name, _compound_bonus(target_index, attributes)))

        difficulty = DIFFICULTIES[target_index - 1]
        furnace_pair = FURNACES[difficulty]
        for variant_index, (name, bonuses) in enumerate(variants):
            serial += 1
            effect: dict[str, object] = {
                "类型": "境界突破",
                "目标境界": target_realm_id,
            }
            if bonuses:
                effect["永久属性"] = bonuses
                bonus_text = "、".join(
                    f"{key}+{value}" for key, value in bonuses.items()
                )
                description = (
                    f"用于突破至{target_name}境，突破完成后永久获得{bonus_text}。"
                )
            else:
                description = (
                    f"用于突破至{target_name}境，只开启后五级修行，不增加永久属性。"
                )
            pills.append(
                {
                    "编号": f"140{serial:03d}",
                    "名称": name,
                    "说明": description,
                    "权重": 310000 + target_index * 100 + variant_index,
                    "使用效果": effect,
                    "参考价": 10000 + target_index * 9000 + variant_index * 1200,
                }
            )
            recipes.append(
                {
                    "编号": f"150{serial:03d}",
                    "名称": f"{name}方",
                    "炼制难度": difficulty,
                    "炉法": furnace_pair[variant_index % len(furnace_pair)],
                    "成丹": f"140{serial:03d}",
                }
            )
    return pills, recipes


def validate(
    realms: list[dict[str, object]],
    pills: list[dict[str, object]],
    recipes: list[dict[str, object]],
) -> None:
    if len(realms) != 20 or len(pills) != 189 or len(recipes) != 189:
        raise ValueError(
            f"数量错误：境界 {len(realms)}，突破丹 {len(pills)}，丹方 {len(recipes)}"
        )
    for label, rows in (("境界", realms), ("突破丹", pills), ("突破丹方", recipes)):
        for field in ("编号", "名称"):
            values = [str(row[field]) for row in rows]
            if len(values) != len(set(values)):
                raise ValueError(f"{label}{field}重复")
    if any(not str(row["编号"]).startswith("14") for row in pills):
        raise ValueError("突破丹必须使用 14 前缀")
    if any(not str(row["编号"]).startswith("15") for row in recipes):
        raise ValueError("突破丹方必须使用 15 前缀")
    if len({int(row["权重"]) for row in pills}) != len(pills):
        raise ValueError("突破丹权重重复")

    realm_ids = {str(row["编号"]) for row in realms}
    pill_ids = {str(row["编号"]) for row in pills}
    plain_count = 0
    target_counts: dict[str, int] = {}
    for pill in pills:
        effect = pill["使用效果"]
        target = str(effect["目标境界"])
        if target not in realm_ids or target == "510001":
            raise ValueError(f"突破丹目标境界错误：{pill['编号']} -> {target}")
        target_counts[target] = target_counts.get(target, 0) + 1
        bonuses = effect.get("永久属性")
        if bonuses is None:
            plain_count += 1
            continue
        if not bonuses or not set(bonuses) <= VALID_ATTRIBUTES:
            raise ValueError(f"突破丹永久属性错误：{pill['编号']}")
        if any(value <= 0 for value in bonuses.values()):
            raise ValueError(f"突破丹永久属性必须为正数：{pill['编号']}")
    if plain_count != 19:
        raise ValueError(f"正丹数量错误：{plain_count}")
    if tuple(target_counts.values()) != CHOICE_COUNTS:
        raise ValueError(f"各境界丹药数量错误：{tuple(target_counts.values())}")

    for recipe in recipes:
        if str(recipe["成丹"]) not in pill_ids:
            raise ValueError(f"丹方引用未知突破丹：{recipe['编号']}")
        if int(recipe["炼制难度"]) not in FURNACES:
            raise ValueError(f"丹方难度错误：{recipe['编号']}")
        if str(recipe["炉法"]) not in FURNACES[int(recipe["炼制难度"])]:
            raise ValueError(f"丹方炉法与难度不符：{recipe['编号']}")


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    realm_rows = build_realms()
    pill_rows, recipe_rows = build_pills_and_recipes()
    validate(realm_rows, pill_rows, recipe_rows)
    write(REALM_OUTPUT, realm_rows)
    write(PILL_OUTPUT, pill_rows)
    write(RECIPE_OUTPUT, recipe_rows)
    print(
        f"已生成 {len(realm_rows)} 个境界、{len(pill_rows)} 枚突破丹和 "
        f"{len(recipe_rows)} 张突破丹方"
    )
