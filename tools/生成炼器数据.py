"""从正式物品与战斗机制生成炼器归类和首批器律。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MINERAL_VEINS = ("天金", "玄铁", "坤石", "离火", "玄水", "青木", "风罡", "雷罡", "星砂")
BEAST_VEINS = ("岳骨", "天风", "玄甲", "赤炎", "沧溟", "幽毒", "灵识", "荒血")

FORGE_METHODS = {
    "灵器": [
        ("太白开锋", (("天金", 2), ("玄铁", 2))),
        ("玄铁藏刃", (("玄铁", 2), ("坤石", 2))),
        ("离火醒器", (("离火", 2), ("天金", 2))),
        ("沧溟淬灵", (("玄水", 2), ("天金", 2))),
        ("青木养纹", (("青木", 2), ("坤石", 2))),
        ("罡风砺形", (("风罡", 2), ("天金", 2))),
        ("雷池点窍", (("雷罡", 2), ("玄铁", 2))),
        ("星砂定魄", (("星砂", 2), ("坤石", 2), ("玄水", 1))),
    ],
    "法器": [
        ("金火交鸣", (("天金", 2), ("离火", 2), ("风罡", 1))),
        ("玄坤镇炉", (("玄铁", 2), ("坤石", 3))),
        ("水木涵真", (("玄水", 2), ("青木", 2), ("星砂", 1))),
        ("风雷刻印", (("风罡", 2), ("雷罡", 2), ("天金", 1))),
        ("离坤承煞", (("离火", 2), ("坤石", 2), ("玄铁", 2))),
        ("星河洗锋", (("星砂", 2), ("玄水", 2), ("天金", 2))),
        ("青罡续脉", (("青木", 2), ("风罡", 2), ("雷罡", 2))),
        ("九材合契", (("天金", 1), ("玄铁", 1), ("坤石", 1), ("离火", 1), ("玄水", 1), ("青木", 1), ("星砂", 1))),
    ],
    "法宝": [
        ("三曜铸魂", (("天金", 3), ("离火", 2), ("星砂", 2))),
        ("玄岳不移", (("玄铁", 3), ("坤石", 3), ("玄水", 1))),
        ("沧海生木", (("玄水", 3), ("青木", 3), ("风罡", 1))),
        ("风雷炼界", (("风罡", 3), ("雷罡", 3), ("天金", 1))),
        ("离火照玄", (("离火", 3), ("玄铁", 2), ("星砂", 2))),
        ("五炁朝器", (("天金", 2), ("坤石", 2), ("离火", 1), ("玄水", 1), ("青木", 1), ("风罡", 1))),
        ("星罗密铸", (("星砂", 3), ("天金", 2), ("雷罡", 2), ("玄水", 1))),
        ("乾坤交泰", (("坤石", 3), ("玄铁", 2), ("青木", 2), ("离火", 2))),
    ],
    "后天灵宝": [
        ("九霄铸命", (("风罡", 3), ("雷罡", 3), ("天金", 2), ("星砂", 1))),
        ("玄黄载道", (("坤石", 4), ("玄铁", 3), ("青木", 2))),
        ("水火既济", (("玄水", 3), ("离火", 3), ("天金", 2), ("星砂", 1))),
        ("太虚凝真", (("星砂", 3), ("风罡", 2), ("玄水", 2), ("天金", 2), ("青木", 1))),
        ("五行归藏", (("天金", 2), ("坤石", 2), ("离火", 2), ("玄水", 2), ("青木", 2))),
        ("万象合炉", (("天金", 2), ("玄铁", 2), ("坤石", 2), ("离火", 1), ("玄水", 1), ("青木", 1), ("风罡", 1), ("雷罡", 1))),
        ("周天炼界", (("风罡", 2), ("雷罡", 2), ("星砂", 2), ("天金", 2), ("玄铁", 2), ("坤石", 2))),
        ("混元一炁", (("天金", 2), ("玄铁", 1), ("坤石", 2), ("离火", 1), ("玄水", 2), ("青木", 1), ("风罡", 1), ("雷罡", 1), ("星砂", 1))),
    ],
}

LAW_GROUPS = {
    "攻伐": ["太白惊鸿", "赤霄饮羽", "九曜摧城", "斩岳沉渊", "碎星横霄", "天刑照骨", "无归劫锋", "混元裂界"],
    "守御": ["玄武负岳", "金阙镇心", "不动山河", "镜海回澜", "天门垂壁", "乾坤护命", "万劫不侵", "太虚藏身"],
    "应变": ["流光换影", "逆水回舟", "移星易宿", "风雷转关", "照夜返真", "一念回天", "镜花代劫", "万象更生"],
    "牵制": ["玄门锁月", "缚龙沉渊", "九宫停云", "太阴蚀脉", "断海封潮", "天罗禁行", "无漏镇神", "归墟绝响"],
    "同契": ["青冥连枝", "山海同心", "星火相传", "玄黄共命", "金兰照胆", "众妙归一", "四极扶摇", "万灵拱辰"],
    "行气": ["沧浪回炁", "太乙周天", "紫府开阖", "玄关纳海", "灵台返照", "气海潮生", "九转还元", "混元不息"],
    "时序": ["先天一刻", "追光逐隙", "斗转星移", "岁轮回照", "刹那生灭", "天机早见", "万法候时", "太虚折岁"],
    "绝境": ["一息悬命", "劫火余生", "枯木逢春", "孤星不坠", "血尽锋回", "破釜沉舟", "绝处开天", "万劫归真"],
}

MECHANISMS = (
    "600641", "600642", "600013", "600014", "600015", "600020", "600022", "600150",
    "600016", "600021", "600023", "600151", "600645", "600646", "601521", "601525",
    "600018", "600019", "600497", "600498", "600502", "600765", "601261", "601279",
    "600961", "600962", "600964", "600966", "600978", "600979", "600500", "600508",
    "600149", "600276", "600340", "600436", "601482", "601486", "601498", "601499",
    "600278", "600438", "600440", "600513", "600514", "600518", "600527", "601342",
    "600433", "600434", "600435", "600447", "600749", "601581", "601585", "601598",
    "600284", "600337", "600338", "600344", "600725", "601583", "601538", "601599",
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mineral_veins(name: str, index: int) -> tuple[str, str]:
    if any(word in name for word in ("火山", "熔岩", "丹崖", "温泉")):
        primary = "离火"
    elif any(word in name for word in ("雷谷",)):
        primary = "雷罡"
    elif any(word in name for word in ("风谷", "云", "高地", "高原", "山口")):
        primary = "风罡"
    elif any(word in name for word in ("冰谷", "寒沼", "海岸", "湖", "河", "溪", "江岸", "湿地", "沙洲", "水网", "泉谷")):
        primary = "玄水"
    elif any(word in name for word in ("林", "竹", "草", "沃野", "原野")):
        primary = "青木"
    elif any(word in name for word in ("黑岩", "石岭", "岩地", "断崖", "山脊", "峡谷")):
        primary = "玄铁"
    elif any(word in name for word in ("沙地", "裂隙", "荒丘")):
        primary = "星砂"
    else:
        primary = "坤石"
    start = MINERAL_VEINS.index(primary)
    side = MINERAL_VEINS[(start + 1 + index % (len(MINERAL_VEINS) - 1)) % len(MINERAL_VEINS)]
    if side == primary:
        side = MINERAL_VEINS[(start + 1) % len(MINERAL_VEINS)]
    return primary, side


def beast_vein(name: str) -> str:
    if any(word in name for word in ("毒蛛", "毒蝎", "赤蝎")):
        return "幽毒"
    if any(word in name for word in ("水蛇", "玄鼋", "海狼")):
        return "沧溟"
    if any(word in name for word in ("火蛇", "火蝠", "火鸦")):
        return "赤炎"
    if any(word in name for word in ("鹰", "隼", "雕", "石蝠", "溪蝠", "白蝠")):
        return "天风"
    if any(word in name for word in ("甲蜥", "石蜥", "泽蜥", "翼蜥", "鳞蜥", "岩蟒", "甲熊", "铁犀")):
        return "玄甲"
    if "灵狸" in name:
        return "灵识"
    if any(word in name for word in ("猎犬", "山犬", "风犬", "狼王", "苍豹")):
        return "荒血"
    return "岳骨"


def build_rules() -> None:
    mineral_files = sorted((DATA / "内容/物品/灵矿").glob("灵矿-*.json"), key=lambda value: value.stem)
    mineral_rows = []
    for index, path in enumerate(mineral_files):
        primary, side = mineral_veins(path.stem, index)
        mineral_rows.append({"灵矿池": path.stem, "本脉": primary, "旁脉": side})
    counts = Counter(str(row["本脉"]) for row in mineral_rows)
    for vein in MINERAL_VEINS:
        while counts[vein] < 3:
            donor = max(MINERAL_VEINS, key=lambda value: counts[value])
            row = next(
                value
                for value in reversed(mineral_rows)
                if value["本脉"] == donor and value["旁脉"] != vein
            )
            row["本脉"] = vein
            if row["旁脉"] == vein:
                row["旁脉"] = donor
            counts[donor] -= 1
            counts[vein] += 1
    write_json(DATA / "规则/炼器/归脉.json", mineral_rows)

    beast_files = sorted((DATA / "内容/物品/兽宝").glob("兽宝-*.json"), key=lambda value: value.stem)
    guide_rows = [{"兽宝池": path.stem, "兽脉": beast_vein(path.stem)} for path in beast_files]
    write_json(DATA / "规则/炼器/归引.json", guide_rows)

    method_rows = []
    for tier, methods in FORGE_METHODS.items():
        for name, requirements in methods:
            method_rows.append(
                {
                    "名称": name,
                    "器阶": tier,
                    "铸势": f"依{name}之序汲取诸矿精华，使兽引与器胚相合。",
                    "辅材": [{"铸脉": vein, "份数": count} for vein, count in requirements],
                }
            )
    write_json(DATA / "规则/炼器/铸法.json", method_rows)


def build_laws() -> None:
    tiers = ("灵器", "法器", "法宝", "后天灵宝")
    beast_pairs = (
        ("岳骨", "天风"), ("玄甲", "赤炎"), ("沧溟", "幽毒"), ("灵识", "荒血"),
        ("岳骨", "玄甲"), ("天风", "灵识"), ("赤炎", "荒血"), ("沧溟", "灵识"),
    )
    output: dict[str, list[dict[str, object]]] = {name: [] for name in LAW_GROUPS}
    mechanism_index = 0
    for group, names in LAW_GROUPS.items():
        for local_index, name in enumerate(names):
            tier = tiers[(local_index // 2) % len(tiers)]
            method = FORGE_METHODS[tier][(mechanism_index + local_index) % 8][0]
            guides = list(beast_pairs[(mechanism_index + local_index) % len(beast_pairs)])
            if tier in {"法宝", "后天灵宝"}:
                extra = BEAST_VEINS[(mechanism_index + local_index + 3) % len(BEAST_VEINS)]
                while extra in guides:
                    extra = BEAST_VEINS[(BEAST_VEINS.index(extra) + 1) % len(BEAST_VEINS)]
                guides.append(extra)
            identity = f"70{mechanism_index + 1:04d}"
            output[group].append(
                {
                    "编号": identity,
                    "名称": name,
                    "器阶": tier,
                    "铸法": method,
                    "兽引": guides,
                    "能力": [
                        {
                            "能力": "被动技能",
                            "名称": name,
                            "结算顺序": 1,
                            "效果": [{"能力": "引用被动机制", "机制": MECHANISMS[mechanism_index]}],
                        }
                    ],
                }
            )
            mechanism_index += 1
    for group, values in output.items():
        write_json(DATA / f"内容/炼器/器律-{group}.json", values)


if __name__ == "__main__":
    build_rules()
    build_laws()
