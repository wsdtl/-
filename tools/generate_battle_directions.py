"""生成264条正式战斗方向及其静态中文JSON资源。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "内容"
TECHNIQUE_DIR = DATA / "物品" / "功法"
ENCHANTMENT_DIR = DATA / "物品" / "附魔技能书"
GEM_DIR = DATA / "物品" / "宝石"
DIRECTION_MECHANISM_DIR = DATA / "战斗机制" / "方向"
WORLD_DIR = DATA / "世界"

AFFIXES = (
    "气血绵长",
    "神完气足",
    "攻伐精进",
    "守中抱一",
    "身轻如燕",
    "照见破绽",
    "血气回流",
    "洞察秋毫",
    "铁壁横江",
    "裂甲行锋",
    "敛息归元",
    "百炼其身",
)
DIMENSIONS = (
    "输出",
    "生存",
    "控制",
    "续航",
    "启动速度",
    "资源效率",
    "稳定性",
    "团队价值",
)


def _engine(
    key: str,
    direction_root: str,
    status: str,
    target: str,
    category: str,
    mode: str,
    roots: tuple[str, str, str],
    images: tuple[str, str, str],
    attributes: tuple[str, str],
    modifiers: dict[str, float],
    main_metric: str,
    support_metric: str,
    advantage: str,
    weakness: str,
    adjustments: dict[str, int],
    conflicts: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "key": key,
        "direction_root": direction_root,
        "status": status,
        "target": target,
        "category": category,
        "mode": mode,
        "symbols": tuple(f"{root}{image}" for root in roots for image in images),
        "attributes": attributes,
        "modifiers": modifiers,
        "main_metric": main_metric,
        "support_metric": support_metric,
        "advantage": advantage,
        "weakness": weakness,
        "adjustments": adjustments,
        "conflicts": conflicts,
    }


ENGINES = (
    _engine("离火", "赤燧", "离火灼痕", "当前目标", "负面", "dot", ("赤", "炎", "烬"), ("燧", "轮", "莲"), ("攻击", "技能威力"), {}, "灼痕有效层数", "持续伤害覆盖率", "擅长拖长战线后持续压低血气", "惧怕净化与快速决胜", {"输出": 5, "续航": 2, "启动速度": -3}, ("玄冰",)),
    _engine("玄冰", "玄霜", "玄冰寒魄", "当前目标", "负面", "debuff", ("霜", "冰", "雪"), ("华", "魄", "川"), ("速度", "控制命中率"), {"速度": -3, "蓄势速度": -2}, "寒魄压速总量", "敌方行动延迟", "擅长压低高速对手的行动频率", "惧怕控制免疫与稳定恢复", {"控制": 5, "生存": 2, "输出": -2}, ("离火",)),
    _engine("雷枢", "九霄", "雷枢电印", "当前目标", "负面", "mark", ("雷", "电", "霆"), ("枢", "印", "池"), ("暴击率", "速度"), {"抗暴率": -1}, "电印引爆收益", "暴击触发次数", "擅长在短行动窗内连续引爆印记", "惧怕高抗暴与伤害减免", {"输出": 4, "启动速度": 4, "稳定性": -3}),
    _engine("剑意", "青锋", "青锋剑意", "自身", "正面", "buff", ("青", "明", "流"), ("锋", "刃", "虹"), ("攻击", "暴击率"), {"攻击": 0.5, "暴击率": 0.25}, "剑意转化伤害", "有效暴击次数", "擅长稳定积累后形成连续剑势", "惧怕缴械式技能封锁", {"输出": 4, "稳定性": 3, "生存": -2}),
    _engine("刀势", "断岳", "断岳刀势", "自身", "正面", "buff", ("断", "裂", "沉"), ("岳", "锋", "关"), ("固定穿透", "技能威力"), {"固定穿透": 0.5, "技能威力": 1}, "刀势破防收益", "有效穿透伤害", "擅长以重击突破高防目标", "惧怕闪避与行动压制", {"输出": 5, "控制": -2, "启动速度": -2}, ("影步",)),
    _engine("毒瘴", "碧瘴", "碧瘴毒种", "当前目标", "负面", "dot", ("碧", "幽", "腐"), ("瘴", "藤", "蛊"), ("技能威力", "控制命中率"), {"治疗加成": -1.5}, "毒种累计伤害", "受疗压制总量", "擅长克制依赖治疗的持久构筑", "惧怕频繁净化与状态免疫", {"输出": 3, "控制": 2, "续航": 2, "启动速度": -2}, ("净明",)),
    _engine("血煞", "血河", "血河煞意", "自身", "正面", "buff", ("血", "煞", "殷"), ("河", "锋", "月"), ("伤害加成", "吸血率"), {"伤害加成": 1, "吸血率": 0.5}, "损血转化效率", "吸血回补量", "擅长在受伤后反向提高威胁", "惧怕斩杀与持续控制", {"输出": 4, "续航": 4, "稳定性": -3}, ("生息",)),
    _engine("灵潮", "沧溟", "沧溟潮息", "自身", "正面", "resource", ("沧", "潮", "澜"), ("溟", "眼", "汐"), ("精神上限", "精神恢复"), {"精神恢复": 1}, "精神周转次数", "技能空档率", "擅长支撑高消耗技能长期运转", "惧怕精神抽取与资源封锁", {"资源效率": 6, "续航": 3, "输出": -2}, ("夺元",)),
    _engine("罡盾", "镇岳", "镇岳罡势", "自身", "正面", "shield", ("镇", "玄", "厚"), ("岳", "壁", "城"), ("护盾上限", "防御"), {"防御": 0.5, "伤害减免": 0.2}, "有效护盾吸收", "破盾前承伤量", "擅长承受稳定的直接伤害", "惧怕资源剥夺与持续伤害", {"生存": 7, "团队价值": 2, "启动速度": -2}, ("剑意",)),
    _engine("影步", "惊鸿", "惊鸿影痕", "自身", "正面", "tempo", ("惊", "飞", "掠"), ("鸿", "影", "羽"), ("速度", "闪避率"), {"速度": 2, "闪避率": 0.5}, "额外行动收益", "闪避后推进量", "擅长抢占行动次序并规避重击", "惧怕高命中与无法闪避的伤害", {"启动速度": 7, "生存": 2, "稳定性": -2}, ("刀势", "蓄势")),
    _engine("破绽", "裂甲", "裂甲破绽", "当前目标", "负面", "debuff", ("裂", "穿", "摧"), ("甲", "隙", "垒"), ("固定穿透", "比例穿透"), {"防御": -1, "伤害减免": -0.5}, "破绽增伤收益", "防御削减覆盖率", "擅长协助全队突破高防目标", "惧怕快速驱散与低防高血目标", {"输出": 4, "团队价值": 4, "续航": -2}),
    _engine("禁印", "封神", "封神禁印", "当前目标", "负面", "control", ("封", "禁", "锁"), ("神", "印", "窍"), ("控制命中率", "速度"), {"控制抵抗率": -2, "韧性": -1}, "控制成功回合", "禁印覆盖率", "擅长打断依赖技能的完整循环", "惧怕高韧性与控制免疫", {"控制": 8, "输出": -3, "稳定性": -1}),
    _engine("生息", "青莲", "青莲生机", "自身", "正面", "heal", ("青", "玉", "净"), ("莲", "露", "华"), ("治疗加成", "血气恢复"), {"治疗加成": 0.5, "血气恢复": 0.2}, "有效治疗量", "过量治疗占比", "擅长把长期交换转化为血气优势", "惧怕爆发斩杀与受疗压制", {"续航": 8, "团队价值": 2, "输出": -3}, ("血煞",)),
    _engine("反震", "玄甲", "玄甲反震", "自身", "正面", "counter", ("玄", "铁", "沉"), ("甲", "镜", "山"), ("反击率", "格挡率"), {"反击率": 1, "格挡率": 1}, "反击有效伤害", "格挡触发次数", "擅长惩罚高频直接攻击", "惧怕持续伤害与资源压制", {"生存": 5, "输出": 3, "启动速度": -2}),
    _engine("连势", "千机", "千机连势", "自身", "正面", "combo", ("千", "叠", "连"), ("机", "环", "星"), ("连击率", "普通攻击威力"), {"连击率": 1, "普通攻击威力": 1}, "连击追加伤害", "连续触发稳定性", "擅长通过高频攻击放大附魔收益", "惧怕反伤与格挡反制", {"输出": 4, "稳定性": 4, "生存": -2}),
    _engine("蓄势", "太虚", "太虚蓄势", "自身", "正面", "charge", ("太", "虚", "空"), ("渊", "轮", "门"), ("技能威力", "蓄势速度"), {"技能威力": 1.5, "蓄势速度": 1}, "蓄势技能收益", "冷却空档回报", "擅长以较长准备换取高额单次收益", "惧怕行动打断与持续压制", {"输出": 5, "资源效率": 2, "启动速度": -5}, ("影步",)),
    _engine("夺元", "吞星", "吞星夺元", "当前目标", "负面", "drain", ("吞", "噬", "夺"), ("星", "元", "海"), ("精神上限", "精神消耗修正"), {"精神恢复": -1, "精神消耗修正": -1}, "敌方精神损失", "技能封锁回合", "擅长让高消耗构筑失去施法能力", "惧怕普通攻击与低消耗循环", {"控制": 4, "资源效率": 5, "输出": -3}, ("灵潮",)),
    _engine("咒蚀", "九幽", "九幽咒蚀", "当前目标", "负面", "debuff", ("九", "幽", "冥"), ("咒", "烙", "渊"), ("控制命中率", "伤害加成"), {"伤害加成": -1, "治疗加成": -1}, "减益有效回合", "敌方输出损失", "擅长同时削弱进攻与恢复能力", "惧怕净化和短时爆发", {"控制": 4, "生存": 3, "输出": -2}, ("净明",)),
    _engine("净明", "明光", "明光无垢", "自身", "正面", "cleanse", ("明", "净", "曜"), ("光", "镜", "心"), ("控制抵抗率", "韧性"), {"控制抵抗率": 1.5, "韧性": 1}, "净化有效状态数", "控制抵抗收益", "擅长维持自身循环不被负面状态打断", "惧怕纯粹高额直接伤害", {"稳定性": 7, "生存": 3, "输出": -3}, ("毒瘴", "咒蚀")),
    _engine("命灯", "轮回", "轮回命灯", "自身", "正面", "fatal", ("轮", "返", "生"), ("回", "灯", "门"), ("血气上限", "伤害减免"), {"血气上限": 1, "伤害减免": 0.2}, "濒死保护价值", "残血存活回合", "擅长承受一次决定性爆发并继续作战", "惧怕多段追击与斩杀补刀", {"生存": 8, "稳定性": 2, "输出": -4}),
    _engine("时隙", "天机", "天机时隙", "自身", "正面", "tempo", ("天", "时", "辰"), ("机", "轮", "晷"), ("冷却缩减", "速度"), {"冷却缩减": 0.5, "速度": 1}, "冷却节省回合", "额外行动次数", "擅长调整技能间隔形成连续施法", "惧怕沉默与精神枯竭", {"启动速度": 5, "资源效率": 4, "输出": -2}),
    _engine("五行", "五行", "五行轮转", "自身", "正面", "random", ("金", "木", "水"), ("火", "土", "轮"), ("攻击", "防御"), {"攻击": 0.25, "防御": 0.25, "速度": 0.25}, "五行有利结果", "随机结果方差", "擅长用多类收益适应不同敌人", "惧怕需要精确节奏的短局", {"稳定性": -4, "团队价值": 3, "资源效率": 2}),
)

ENGINE_DAMAGE_FACTORS = {
    "离火": 0.50,
    "玄冰": 1.20,
    "雷枢": 1.20,
    "剑意": 0.70,
    "刀势": 1.15,
    "毒瘴": 0.95,
    "血煞": 1.15,
    "灵潮": 1.35,
    "罡盾": 0.65,
    "影步": 1.15,
    "破绽": 1.25,
    "禁印": 1.30,
    "生息": 0.60,
    "反震": 1.30,
    "连势": 1.30,
    "蓄势": 1.30,
    "夺元": 1.40,
    "咒蚀": 1.20,
    "净明": 2.00,
    "命灯": 0.60,
    "时隙": 1.25,
    "五行": 0.55,
}


def _objective(
    key: str,
    direction_suffix: str,
    description: str,
    actions: tuple[str, str, str],
    gem_terms: tuple[str, str, str],
    attributes: tuple[str, str],
    damage_percent: int,
    event: str,
    relation: str,
    main_metric: str,
    support_metric: str,
    advantage: str,
    weakness: str,
    weights: tuple[int, int, int, int, int, int, int, int],
) -> dict[str, Any]:
    return {
        "key": key,
        "direction_suffix": direction_suffix,
        "description": description,
        "actions": actions,
        "gem_terms": gem_terms,
        "attributes": attributes,
        "damage_percent": damage_percent,
        "event": event,
        "relation": relation,
        "main_metric": main_metric,
        "support_metric": support_metric,
        "advantage": advantage,
        "weakness": weakness,
        "weights": dict(zip(DIMENSIONS, weights, strict=True)),
    }


OBJECTIVES = (
    _objective("爆发", "一念惊霄", "集中资源形成短时高额伤害窗口", ("破霄", "崩岳", "裂空"), ("曜日", "惊星", "破军"), ("暴击率", "暴击伤害"), 80, "暴击后", "自身为来源", "三行动爆发伤害", "爆发资源利用率", "擅长击破准备不足的目标", "爆发落空后存在明显空档", (34, 9, 4, 5, 20, 10, 12, 6)),
    _objective("持续", "九转蚀骨", "通过可延续效果稳定积累总收益", ("蚀骨", "绵劫", "长燃"), ("长生", "岁蚀", "恒河"), ("技能威力", "精神恢复"), 85, "造成伤害后", "自身为来源", "十二行动累计伤害", "持续效果覆盖率", "擅长处理高血量和防御目标", "惧怕净化与快速爆发", (27, 13, 5, 13, 7, 11, 18, 6)),
    _objective("斩杀", "悬锋断命", "根据目标损失血气提高终结能力", ("断命", "追魂", "绝脉"), ("残月", "断魂", "绝命"), ("伤害加成", "固定穿透"), 58, "击杀后", "自身为来源", "低血目标终结率", "无效过量伤害", "擅长结束恢复型目标的战斗", "目标高血阶段压力偏低", (32, 8, 5, 5, 16, 9, 15, 10)),
    _objective("破盾", "摧岳破垒", "将敌方护盾转化为额外打击收益", ("破垒", "摧城", "贯甲"), ("碎岳", "破城", "穿云"), ("固定穿透", "比例穿透"), 106, "护盾破碎后", "自身相关", "护盾转化伤害", "破盾所需行动数", "擅长克制高护盾构筑", "面对无盾目标时部分收益闲置", (29, 10, 5, 5, 12, 10, 17, 12)),
    _objective("控制", "锁魂缚神", "以技能限制和行动延迟压缩敌方回合", ("缚神", "锁魂", "镇念"), ("定魂", "缚龙", "镇海"), ("控制命中率", "速度"), 95, "技能施放后", "自身为来源", "敌方损失行动数", "控制命中稳定性", "擅长打断复杂技能循环", "面对高韧性目标伤害不足", (16, 11, 31, 8, 13, 7, 8, 6)),
    _objective("反击", "借势回锋", "把承受的攻击转化为反制机会", ("回锋", "借势", "返刃"), ("照胆", "回澜", "返照"), ("反击率", "防御"), 100, "格挡后", "自身为承受者", "反击有效伤害", "承伤收益转化率", "擅长克制高频攻击构筑", "敌方不主动攻击时启动较慢", (22, 25, 5, 11, 7, 8, 14, 8)),
    _objective("续命", "归元养命", "用伤害、治疗和恢复形成持久交换优势", ("养命", "回元", "续脉"), ("生息", "还真", "长春"), ("吸血率", "血气恢复"), 70, "恢复后", "自身相关", "有效恢复总量", "血气交换效率", "擅长持续战斗和多轮遭遇", "惧怕斩杀与受疗削弱", (17, 20, 4, 29, 6, 8, 10, 6)),
    _objective("枯元", "截脉枯元", "压低敌方精神并放大其施法空档", ("枯元", "截脉", "断泉"), ("枯海", "绝泉", "断流"), ("精神上限", "精神消耗修正"), 75, "资源消耗后", "自身为来源", "敌方精神损失", "技能封锁行动数", "擅长克制高消耗主动技能", "面对普通攻击构筑收益有限", (17, 10, 24, 8, 8, 21, 8, 4)),
    _objective("追击", "踏虚逐影", "通过行动推进和速度优势增加出手机会", ("逐影", "踏虚", "追风"), ("飞光", "流影", "追月"), ("速度", "蓄势速度"), 80, "闪避后", "自身为承受者", "额外行动次数", "行动条溢出损失", "擅长在长局中建立行动数量优势", "单次行动质量相对较低", (22, 10, 8, 7, 30, 9, 9, 5)),
    _objective("守阵", "四极镇域", "将个人防御转化为队伍稳定性", ("镇域", "守阵", "庇元"), ("四极", "镇海", "护心"), ("护盾上限", "伤害减免"), 42, "获得护盾后", "自身相关", "有效减伤与护盾", "队伍存活行动数", "擅长保护脆弱队友完成循环", "单人进攻压力较低", (12, 31, 7, 14, 6, 7, 9, 14)),
    _objective("化劫", "逆境化劫", "清理不利状态并把压力转为反击资源", ("化劫", "涤尘", "转厄"), ("无垢", "解厄", "澄明"), ("控制抵抗率", "韧性"), 90, "受到伤害后", "自身为承受者", "负面状态清理价值", "压力转化收益", "擅长对抗减益和持续控制", "面对纯伤害时上限偏低", (18, 19, 14, 13, 7, 8, 16, 5)),
    _objective("转轮", "周天转轮", "缩短技能空档并维持主动技能衔接", ("转轮", "周天", "回环"), ("天轮", "周流", "回星"), ("冷却缩减", "精神恢复"), 92, "技能施放后", "自身为来源", "冷却节省行动数", "技能连续施放率", "擅长稳定执行多技能循环", "惧怕精神不足和技能封锁", (24, 9, 7, 8, 17, 20, 11, 4)),
)


def _selector(scope: str) -> dict[str, Any]:
    return {"能力": "选择目标", "范围": scope}


def _read(
    source: str,
    *,
    percent: float = 100,
    attribute: str = "",
    target: str = "",
    status: str = "",
    counter: str = "",
    skill: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"能力": "读取数值", "来源": source, "百分比": percent}
    if attribute:
        value["属性"] = attribute
    if target:
        value["目标"] = _selector(target)
    if status:
        value["状态"] = status
    if counter:
        value["计量"] = counter
    if skill is not None:
        value["技能"] = skill
    return value


def _calculate(method: str, left: Any, right: Any, *, minimum: float | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"能力": "计算数值", "方式": method, "左值": left, "右值": right}
    if minimum is not None:
        value["最低值"] = minimum
    return value


def _counter_name(direction: str) -> str:
    return f"{direction}道蕴"


def _modify_counter(
    direction: str,
    amount: Any,
    *,
    mode: str = "增加",
    maximum: float = 100,
    fail_if_insufficient: bool = True,
) -> dict[str, Any]:
    return {
        "能力": "修改机制计量",
        "目标": _selector("自身"),
        "计量": _counter_name(direction),
        "方式": mode,
        "数值": amount,
        "最低值": 0,
        "最高值": maximum,
        "不足时是否失败": fail_if_insufficient,
    }


def _counter_value(direction: str) -> dict[str, Any]:
    return _read(
        "机制计量",
        target="自身",
        counter=_counter_name(direction),
    )


def _additional_action(name: str, power: float) -> dict[str, Any]:
    return {
        "能力": "追加行动",
        "名称": name,
        "目标": _selector("当前目标"),
        "行动类型": "普通攻击",
        "威力倍率": power,
        "每次主行动最多追加": 1,
    }


def _modify_current_charge(amount: int) -> dict[str, Any]:
    return {
        "能力": "修改蓄势进度",
        "目标": _selector("自身"),
        "技能": {"能力": "选择技能", "范围": "蓄势中的技能"},
        "方式": "增加",
        "数值": amount,
    }


def _damage_value(engine: dict[str, Any], objective: dict[str, Any], percent: float, *, layered: bool = False) -> dict[str, Any]:
    adjusted = percent * float(ENGINE_DAMAGE_FACTORS[engine["key"]])
    value: dict[str, Any] = _read("自身属性", percent=adjusted, attribute="攻击")
    if layered:
        layers = _read("状态层数", target=engine["target"], status=engine["status"])
        layer_damage = _calculate("相乘", layers, _read("自身属性", percent=9, attribute="攻击"))
        value = _calculate("相加", value, layer_damage, minimum=1)
    if objective["key"] == "斩杀":
        value = _calculate("相加", value, _read("目标已损失血气", percent=2), minimum=1)
    elif objective["key"] == "破盾":
        value = _calculate("相加", value, _read("目标当前护盾", percent=35), minimum=1)
    return value


def _damage(name: str, engine: dict[str, Any], objective: dict[str, Any], percent: float, *, layered: bool = False) -> dict[str, Any]:
    return {
        "能力": "造成伤害",
        "名称": name,
        "目标": _selector("当前目标"),
        "数值": _damage_value(engine, objective, percent, layered=layered),
        "伤害形式": "直接",
        "防御规则": "无视防御" if objective["key"] == "破盾" else "普通",
        "能否暴击": objective["key"] in {"爆发", "斩杀", "追击"},
        "能否格挡": objective["key"] not in {"控制", "枯元"},
        "能否触发吸血": objective["key"] in {"爆发", "斩杀", "续命", "追击"},
        "标签": [f"体系:{engine['key']}", f"目标:{objective['key']}", "方向伤害"],
    }


def _state_mapping(engine: dict[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "名称": engine["status"],
        "分类": engine["category"],
        "持续单位": "整场战斗",
        "叠加范围": "同名共享",
        "重复方式": "增加层数",
        "层数": 1,
        "层数上限": 6,
        "标签": [f"体系:{engine['key']}", "方向状态"],
    }
    if engine["modifiers"]:
        value["属性"] = dict(engine["modifiers"])
    if engine["mode"] == "dot":
        value.update(
            {
                "持续单位": "状态承受者行动",
                "持续数值": 3,
                "叠加范围": "按效果来源分组",
                "重复方式": "增加层数并刷新",
                "触发": [
                    {
                        "能力": "状态周期触发",
                        "事件": "行动开始",
                        "效果": [
                            {
                                "能力": "造成伤害",
                                "目标": _selector("自身"),
                                "数值": _read("效果来源属性", percent=1.5, attribute="攻击",),
                                "伤害形式": "持续",
                                "防御规则": "无视防御",
                                "能否暴击": False,
                                "能否格挡": False,
                                "标签": [f"体系:{engine['key']}", "持续伤害"],
                            }
                        ],
                    }
                ],
            }
        )
    return value


def _add_engine_state(engine: dict[str, Any]) -> dict[str, Any]:
    return {
        "能力": "添加状态",
        "目标": _selector(engine["target"]),
        "状态": _state_mapping(engine),
    }


def _consume_engine_state(engine: dict[str, Any], layers: int = 1) -> dict[str, Any]:
    return {
        "能力": "消耗状态层数",
        "目标": _selector(engine["target"]),
        "状态": engine["status"],
        "层数": layers,
        "不足时是否失败": False,
    }


def _remove_engine_state(engine: dict[str, Any]) -> dict[str, Any]:
    return {
        "能力": "移除状态",
        "目标": _selector(engine["target"]),
        "状态": engine["status"],
        "选择全部": True,
    }


def _engine_support(engine: dict[str, Any]) -> list[dict[str, Any]]:
    mode = engine["mode"]
    if mode == "resource":
        return [{"能力": "恢复资源", "目标": _selector("自身"), "资源": "精神", "数值": _read("自身属性", percent=10, attribute="精神上限")}]
    if mode == "shield":
        return [{"能力": "恢复资源", "目标": _selector("自身"), "资源": "护盾", "数值": _read("自身属性", percent=3, attribute="血气上限")}]
    if mode == "heal":
        return [{"能力": "恢复资源", "目标": _selector("自身"), "资源": "血气", "数值": _read("自身已损失血气", percent=3)}]
    if mode == "cleanse":
        return [{"能力": "移除状态", "目标": _selector("自身"), "分类": "负面", "数量": 1, "顺序": "后获得"}]
    if mode == "tempo":
        return [{"能力": "修改行动条", "目标": _selector("自身"), "方式": "增加", "数值": 12}]
    if mode == "drain":
        return [{"能力": "消耗资源", "目标": _selector("当前目标"), "资源": "精神", "数值": 5, "不足时是否失败": False}]
    if mode == "control":
        return [{"能力": "修改行动条", "目标": _selector("当前目标"), "方式": "减少", "数值": 10}]
    if mode == "fatal":
        return [{"能力": "恢复资源", "目标": _selector("自身"), "资源": "血气", "数值": _read("自身已损失血气", percent=2)}]
    if mode == "random":
        return [{"能力": "随机执行", "选项": [
            {"能力": "恢复资源", "目标": _selector("自身"), "资源": "血气", "数值": 2},
            {"能力": "恢复资源", "目标": _selector("自身"), "资源": "精神", "数值": 2},
            {"能力": "修改行动条", "目标": _selector("自身"), "方式": "增加", "数值": 4},
        ], "抽取数量": 1, "是否放回": False}]
    if mode == "counter":
        return [{"能力": "恢复资源", "目标": _selector("自身"), "资源": "护盾", "数值": _read("自身属性", percent=4, attribute="攻击")}]
    if mode == "combo":
        return [_additional_action(f"{engine['status']}追势", 18)]
    if mode == "charge":
        return [_modify_current_charge(1)]
    return [{"能力": "恢复资源", "目标": _selector("自身"), "资源": "精神", "数值": 2}]


def _objective_support(
    direction: str,
    engine: dict[str, Any],
    objective: dict[str, Any],
) -> list[dict[str, Any]]:
    key = objective["key"]
    if key == "爆发":
        return [
            {"能力": "添加状态", "目标": _selector("自身"), "状态": {"名称": f"{direction}锋芒", "分类": "正面", "持续数值": 2, "重复方式": "刷新持续", "属性": {"暴击率": 5, "暴击伤害": 8}}},
            _modify_counter(direction, 14),
        ]
    if key == "持续":
        return [
            {"能力": "延长状态", "目标": _selector(engine["target"]), "状态": engine["status"], "持续数值": 1},
            {"能力": "恢复资源", "目标": _selector("自身"), "资源": "精神", "数值": 3},
            _modify_counter(direction, 10),
        ]
    if key == "斩杀":
        return [
            {"能力": "修改行动条", "目标": _selector("自身"), "方式": "增加", "数值": 12},
            _modify_counter(direction, _read("目标已损失血气", percent=2, target="当前目标")),
        ]
    if key == "破盾":
        return [
            {"能力": "添加状态", "目标": _selector("当前目标"), "状态": {"名称": f"{direction}崩甲", "分类": "负面", "持续数值": 2, "重复方式": "刷新持续", "属性": {"防御": -3}}},
            _modify_counter(direction, _read("目标当前护盾", percent=5, target="当前目标")),
        ]
    if key == "控制":
        return [
            {"能力": "添加状态", "目标": _selector("当前目标"), "状态": {"名称": f"{direction}锁式", "分类": "控制", "持续数值": 1, "重复方式": "刷新持续", "行动限制": ["技能"], "是否进行控制判定": True, "基础控制命中率": 75, "是否受韧性影响": True}},
            {"能力": "修改行动条", "目标": _selector("当前目标"), "方式": "减少", "数值": 8},
            _modify_counter(direction, 12),
        ]
    if key == "反击":
        return [
            _additional_action(f"{direction}借势", 12),
            _modify_counter(direction, 12),
        ]
    if key == "续命":
        return [
            {"能力": "恢复资源", "目标": _selector("自身"), "资源": "血气", "数值": _read("自身已损失血气", percent=8)},
            _modify_counter(direction, _read("本次恢复", percent=10)),
        ]
    if key == "枯元":
        return [
            {"能力": "消耗资源", "目标": _selector("当前目标"), "资源": "精神", "数值": 7, "不足时是否失败": False},
            _modify_counter(direction, _read("本次资源消耗", percent=20)),
        ]
    if key == "追击":
        return [
            _additional_action(f"{direction}逐影", 15),
            {"能力": "修改行动条", "目标": _selector("自身"), "方式": "增加", "数值": 8},
            _modify_counter(direction, 10),
        ]
    if key == "守阵":
        return [
            {"能力": "恢复资源", "目标": _selector("自身"), "资源": "护盾", "数值": _read("自身属性", percent=11, attribute="血气上限")},
            _modify_counter(direction, 12),
        ]
    if key == "化劫":
        return [
            {"能力": "移除状态", "目标": _selector("自身"), "分类": "负面", "数量": 1, "顺序": "后获得"},
            _modify_counter(direction, 12),
        ]
    return [
        {"能力": "修改技能冷却", "目标": _selector("自身"), "技能": {"能力": "选择技能", "范围": "冷却中的技能", "排序": "冷却从高到低", "数量": 1}, "方式": "减少", "数值": 1},
        _modify_current_charge(1),
        {"能力": "恢复资源", "目标": _selector("自身"), "资源": "精神", "数值": 3},
        _modify_counter(direction, 10),
    ]


def _listener(event: str, relation: str, effects: list[dict[str, Any]], *, battle_limit: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "能力": "监听事件",
        "事件": event,
        "事件关系": relation,
        "每次行动最多触发": 1,
        "效果": effects,
    }
    if battle_limit is not None:
        value["每场战斗最多触发"] = battle_limit
    return value


def _finisher(
    direction: str,
    engine: dict[str, Any],
    objective: dict[str, Any],
    name: str,
    percent: float,
) -> dict[str, Any]:
    return {
        "能力": "条件执行",
        "条件": [
            {
                "能力": "数值条件",
                "左值": _counter_value(direction),
                "比较": "大于等于",
                "右值": 40,
            }
        ],
        "成立效果": [
            _damage(name, engine, objective, percent * 1.12, layered=True),
            *_objective_support(direction, engine, objective),
            _modify_counter(direction, 40, mode="减少"),
            _remove_engine_state(engine),
        ],
        "不成立效果": [
            _damage(name, engine, objective, percent * 0.58, layered=True),
            _modify_counter(direction, 12),
            _add_engine_state(engine),
        ],
    }


def _team_defense_listener(
    direction: str,
    engine: dict[str, Any],
    objective: dict[str, Any],
) -> tuple[str, str, list[dict[str, Any]], int] | None:
    if objective["key"] == "守阵":
        return (
            "造成伤害前",
            "自身与承受者同阵营",
            [
                {
                    "能力": "分摊伤害",
                    "名称": f"{direction}同阵分伤",
                    "目标": _selector("自身"),
                    "比例": 18,
                },
                _modify_counter(direction, 8),
            ],
            4,
        )
    if objective["key"] == "化劫":
        return (
            "造成伤害前",
            "自身与承受者同阵营",
            [
                {
                    "能力": "转移伤害",
                    "名称": f"{direction}代劫",
                    "目标": _selector("自身"),
                    "数值": _read("自身属性", percent=18, attribute="防御"),
                },
                *_engine_support(engine),
                _modify_counter(direction, 8),
            ],
            4,
        )
    return None


def _direction_mechanisms(direction: str, engine: dict[str, Any], objective: dict[str, Any], names: dict[str, list[str]]) -> tuple[dict[str, Any], list[str], list[str]]:
    active_mechanisms: list[str] = []
    passive_mechanisms: list[str] = []
    mechanisms: dict[str, Any] = {}
    percents = (0.78, 0.66, 0.86, 0.45, 1.18)
    for index in range(5):
        mechanism_id = f"{names['功法'][index]}真解"
        active_mechanisms.append(mechanism_id)
        if index == 0:
            effects = [
                _damage(names["功法"][index], engine, objective, objective["damage_percent"] * percents[index]),
                _add_engine_state(engine),
                _modify_counter(direction, 8),
            ]
        elif index == 1:
            effects = [_damage(names["功法"][index], engine, objective, objective["damage_percent"] * percents[index]), *_objective_support(direction, engine, objective), _add_engine_state(engine)]
        elif index == 2:
            effects = [
                _damage(names["功法"][index], engine, objective, objective["damage_percent"] * percents[index], layered=True),
                _consume_engine_state(engine, 1),
                _modify_counter(direction, 12),
            ]
        elif index == 3:
            effects = [*_engine_support(engine), *_objective_support(direction, engine, objective), _add_engine_state(engine)]
        else:
            effects = [
                _finisher(
                    direction,
                    engine,
                    objective,
                    names["功法"][index],
                    objective["damage_percent"] * percents[index],
                )
            ]
        mechanisms[mechanism_id] = {"能力": "顺序执行", "效果": effects}

    passive_specs = [
        ("普通攻击后", "自身为来源", [_add_engine_state(engine), _modify_counter(direction, 5)], None),
        ("技能施放后", "自身为来源", [*_engine_support(engine), _add_engine_state(engine), _modify_counter(direction, 6)], None),
        ("受到伤害后", "自身为承受者", [*_engine_support(engine), _modify_counter(direction, 4)], None),
        (objective["event"], objective["relation"], _objective_support(direction, engine, objective), 4),
    ]
    team_spec = _team_defense_listener(direction, engine, objective)
    if team_spec is not None:
        passive_specs[-1] = team_spec
    for offset, (event, relation, effects, limit) in enumerate(passive_specs, start=5):
        mechanism_id = f"{names['功法'][offset]}真传"
        passive_mechanisms.append(mechanism_id)
        mechanisms[mechanism_id] = _listener(event, relation, effects, battle_limit=limit)

    enchant_events = [
        ("普通攻击后", "自身为来源", [_add_engine_state(engine)]),
        ("技能施放后", "自身为来源", [_add_engine_state(engine)]),
        ("暴击后", "自身为来源", _objective_support(direction, engine, objective)),
        ("造成伤害后", "自身为来源", [{"能力": "恢复资源", "目标": _selector("自身"), "资源": "精神", "数值": 3}]),
        ("受到伤害后", "自身为承受者", _engine_support(engine)),
        ("格挡后", "自身为承受者", _engine_support(engine)),
        ("护盾破碎后", "自身相关", [*_objective_support(direction, engine, objective), _add_engine_state(engine)]),
        ("恢复后", "自身相关", [{"能力": "修改行动条", "目标": _selector("自身"), "方式": "增加", "数值": 8}]),
        ("击杀后", "自身为来源", [*_engine_support(engine), *_objective_support(direction, engine, objective)]),
    ]
    if team_spec is not None:
        enchant_events[6] = (team_spec[0], team_spec[1], team_spec[2])
    enchant_mechanisms: list[str] = []
    for index, (event, relation, effects) in enumerate(enchant_events):
        mechanism_id = f"{names['附魔'][index]}器魂"
        enchant_mechanisms.append(mechanism_id)
        mechanisms[mechanism_id] = _listener(event, relation, effects, battle_limit=4 if index in {6, 8} else None)
    return mechanisms, active_mechanisms + passive_mechanisms, enchant_mechanisms


def _names(engine: dict[str, Any], objective: dict[str, Any]) -> dict[str, list[str]]:
    technique_forms = ("诀", "经", "法")
    enchant_forms = ("纹", "篆", "印")
    gem_forms = ("玉", "珠", "晶")
    techniques: list[str] = []
    enchantments: list[str] = []
    gems: list[str] = []
    for index, symbol in enumerate(engine["symbols"]):
        action = objective["actions"][index // 3]
        gem_term = objective["gem_terms"][index // 3]
        form_index = index % 3
        techniques.append(f"{symbol}{action}{technique_forms[form_index]}")
        enchantments.append(f"{symbol}{action}{enchant_forms[form_index]}")
        gems.append(f"{symbol}{gem_term}{gem_forms[form_index]}")
    return {"功法": techniques, "附魔": enchantments, "宝石": gems}


def _metadata(engine: dict[str, Any], objective: dict[str, Any], *, role: str, index: int, direction: str) -> dict[str, Any]:
    needs = [] if index in {0, 5} else [f"战术:{engine['key']}"]
    mutex: list[str] = []
    if role == "主动" and index in {3, 4}:
        mutex = [f"{direction}:{role}:终式选择"]
    elif index in {7, 8}:
        mutex = [f"{direction}:{role}:辅式选择"]
    return {
        "提供标签": [f"战术:{engine['key']}", f"目标:{objective['key']}", f"职责:{role}"],
        "需要标签": needs,
        "禁止标签": [f"战术:{value}" for value in engine["conflicts"]],
        "互斥组": mutex,
    }


def _techniques(direction_index: int, direction: str, engine: dict[str, Any], objective: dict[str, Any], names: dict[str, list[str]], mechanism_ids: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    affix_offset = (direction_index - 1) % len(AFFIXES)
    affix_pool = [AFFIXES[(affix_offset + value) % len(AFFIXES)] for value in range(8)]
    for index, name in enumerate(names["功法"]):
        active = index < 5
        role = "主动" if active else "被动"
        first_attribute = engine["attributes"][index % 2]
        second_attribute = objective["attributes"][(index + 1) % 2]
        fixed_attributes = {
            first_attribute: _attribute_amount(first_attribute, index % 3),
            second_attribute: _attribute_amount(second_attribute, (index + 1) % 3),
        }
        skill = {
            "能力": "主动技能" if active else "被动技能",
            "名称": name,
            ("释放顺序" if active else "结算顺序"): direction_index * 100 + (index + 1 if active else index - 4),
            "效果": [
                {
                    "能力": "引用战斗机制" if active else "引用被动机制",
                    "机制": mechanism_ids[index],
                }
            ],
        }
        if active:
            skill["精神消耗"] = (4, 5, 6, 5, 8)[index]
            skill["冷却回合"] = (2, 3, 4, 5, 6)[index]
            if engine["mode"] == "charge" and index == 4:
                skill["蓄势回合"] = 1
            elif objective["key"] in {"爆发", "破盾", "控制"} and index == 4:
                skill["蓄势回合"] = 1
            elif objective["key"] == "转轮" and index == 2:
                skill["蓄势回合"] = 1
        metadata = _metadata(engine, objective, role=role, index=index, direction=direction)
        result[name] = {
            "说明": f"{direction}的{role}功法，以{engine['status']}衔接{objective['description']}。",
            "权重": 120 + index * 6 + (8 if active and index == 4 else 0),
            "评分": (100 if active else 96) + index * 2,
            "职责": role,
            **metadata,
            "随机词条": affix_pool,
            "组成": [
                {"能力": "固定属性加成", "属性": fixed_attributes},
                skill,
            ],
        }
    return result


def _enchantments(direction_index: int, direction: str, engine: dict[str, Any], objective: dict[str, Any], names: dict[str, list[str]], mechanism_ids: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, name in enumerate(names["附魔"]):
        metadata = _metadata(engine, objective, role="附魔", index=index, direction=direction)
        result[name] = {
            "说明": f"{direction}的本命武器附魔，在{engine['status']}循环中追加{objective['key']}收益。",
            "权重": 110 + index * 7,
            "评分": 82 + index * 2,
            **metadata,
            "组成": [
                {
                    "能力": "被动技能",
                    "名称": name,
                    "结算顺序": direction_index * 100 + 11 + index,
                    "效果": [{"能力": "引用被动机制", "机制": mechanism_ids[index]}],
                }
            ],
        }
    return result


def _gems(direction: str, engine: dict[str, Any], objective: dict[str, Any], names: dict[str, list[str]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    attributes = (*engine["attributes"], *objective["attributes"])
    for index, name in enumerate(names["宝石"]):
        first = attributes[index % len(attributes)]
        second = attributes[(index + 1) % len(attributes)]
        values = {
            first: _attribute_amount(first, index % 3),
            second: _attribute_amount(second, (index + 2) % 3),
        }
        metadata = _metadata(engine, objective, role="宝石", index=index, direction=direction)
        score = 72 + index * 2 + int(sum(abs(float(value)) for value in values.values()) / 3)
        result[name] = {
            "说明": f"{direction}的增幅宝石，强化{first}与{second}，不产生独立技能。",
            "权重": 100 + index * 8,
            "评分": score,
            **metadata,
            "组成": [{"能力": "固定属性加成", "属性": values}],
        }
    return result


def _attribute_amount(attribute: str, tier: int) -> float | int:
    level = max(0, int(tier))
    if attribute in {"血气上限", "护盾上限"}:
        return 8 + level * 3
    if attribute == "精神上限":
        return 5 + level * 2
    if attribute in {"攻击", "防御"}:
        return 2 + level
    if attribute in {"速度", "蓄势速度"}:
        return 3 + level * 2
    return 2 + level


def _direction_definition(direction: str, engine: dict[str, Any], objective: dict[str, Any]) -> dict[str, Any]:
    counter = _counter_name(direction)
    special = {
        "反击": "受击或格挡后追加普通攻击",
        "追击": "取得节奏后追加普通攻击",
        "守阵": "替同阵修士分摊伤害",
        "化劫": "替同阵修士承接部分伤害并化解负面状态",
        "转轮": "推进蓄势并缩减技能冷却",
    }.get(objective["key"], f"以{objective['main_metric']}积累临战优势")
    return {
        "定位": f"以{engine['status']}与{counter}为双核心，{objective['description']}。",
        "核心状态": f"{engine['status']}、{counter}",
        "机制构型": {
            "根基机制": engine["key"],
            "运转方式": engine["mode"],
            "精通目标": objective["key"],
            "临战计量": counter,
            "专属变化": special,
            "终式门槛": 40,
        },
        "核心循环": [
            f"以起手功法建立{engine['status']}，同时积累{counter}",
            f"通过{engine['support_metric']}维持{engine['key']}根基运转",
            f"执行{special}，将{objective['support_metric']}转为实战收益",
            f"{counter}达到40后，以{objective['main_metric']}驱动终式强化分支",
            f"终式消耗40点{counter}并重整{engine['status']}，随后重新起势",
        ],
        "进攻方式": f"主要考察{objective['main_metric']}，并把{engine['main_metric']}转化为有效进攻。",
        "防御方式": f"通过{engine['support_metric']}与{objective['support_metric']}降低循环被打断的概率。",
        "优势场景": [engine["advantage"], objective["advantage"]],
        "弱势场景": [engine["weakness"], objective["weakness"]],
    }


def _normalized_weights(base: dict[str, int], adjustments: dict[str, int]) -> dict[str, int]:
    raw = {key: max(1, int(base[key]) + int(adjustments.get(key, 0))) for key in DIMENSIONS}
    total = sum(raw.values())
    scaled = {key: max(1, int(raw[key] * 100 / total)) for key in DIMENSIONS}
    difference = 100 - sum(scaled.values())
    order = sorted(DIMENSIONS, key=lambda key: raw[key], reverse=True)
    cursor = 0
    while difference:
        key = order[cursor % len(order)]
        if difference > 0:
            scaled[key] += 1
            difference -= 1
        elif scaled[key] > 1:
            scaled[key] -= 1
            difference += 1
        cursor += 1
    return scaled


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clear_generated_files() -> None:
    expected_parent = (ROOT / "data" / "内容" / "物品").resolve()
    for directory in (TECHNIQUE_DIR, ENCHANTMENT_DIR, GEM_DIR):
        resolved = directory.resolve()
        if resolved.parent != expected_parent:
            raise RuntimeError(f"拒绝清理意外目录：{resolved}")
        for path in resolved.glob("*.json"):
            path.unlink()
    resolved_mechanisms = DIRECTION_MECHANISM_DIR.resolve()
    if resolved_mechanisms.parent != (ROOT / "data" / "内容" / "战斗机制").resolve():
        raise RuntimeError(f"拒绝清理意外目录：{resolved_mechanisms}")
    if resolved_mechanisms.exists():
        for path in resolved_mechanisms.glob("*.json"):
            path.unlink()


def _world_npcs() -> list[tuple[Path, list[dict[str, Any]], int]]:
    result: list[tuple[Path, list[dict[str, Any]], int]] = []
    for path in sorted(WORLD_DIR.rglob("*.json"), key=lambda value: value.as_posix()):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not path.stem.endswith("道侣"):
            continue
        for index, npc in enumerate(data):
            if not isinstance(npc, dict):
                raise RuntimeError(f"道侣池存在非对象项：{path}")
            result.append((path, data, index))
    return result


def _remove_enemy_static_loadouts() -> None:
    for path in sorted(WORLD_DIR.rglob("*.json"), key=lambda value: value.as_posix()):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not path.stem.endswith("敌人"):
            continue
        changed = False
        for enemy in data.values():
            if "功法" in enemy:
                del enemy["功法"]
                changed = True
        if changed:
            _write_json(path, data)


def generate() -> None:
    _clear_generated_files()
    assignments = _world_npcs()
    expected = len(ENGINES) * len(OBJECTIVES)
    if len(assignments) != expected:
        raise RuntimeError(f"世界必须正好定义{expected}名道侣，当前为{len(assignments)}名")

    changed_world: dict[Path, list[dict[str, Any]]] = {}
    directions: dict[str, dict[str, Any]] = {}
    direction_index = 0
    for engine in ENGINES:
        for objective in OBJECTIVES:
            direction_index += 1
            direction = f"{engine['direction_root']}{objective['direction_suffix']}"
            names = _names(engine, objective)
            mechanisms, technique_mechanisms, enchantment_mechanisms = _direction_mechanisms(
                direction,
                engine,
                objective,
                names,
            )
            technique_group = f"功法-{direction}"
            enchantment_group = f"物品-附魔-{direction}"
            gem_group = f"物品-宝石-{direction}"
            _write_json(
                DIRECTION_MECHANISM_DIR / f"机制-{direction}.json",
                mechanisms,
            )
            _write_json(
                TECHNIQUE_DIR / f"{technique_group}.json",
                _techniques(direction_index, direction, engine, objective, names, technique_mechanisms),
            )
            _write_json(
                ENCHANTMENT_DIR / f"{enchantment_group}.json",
                _enchantments(direction_index, direction, engine, objective, names, enchantment_mechanisms),
            )
            _write_json(
                GEM_DIR / f"{gem_group}.json",
                _gems(direction, engine, objective, names),
            )
            directions[direction] = _direction_definition(direction, engine, objective)

            world_path, world_data, npc_index = assignments[direction_index - 1]
            npc = world_data[npc_index]
            npc["修行方向"] = direction
            npc["功法池"] = [technique_group]
            npc["附魔池"] = [enchantment_group]
            npc["宝石池"] = [gem_group]
            changed_world[world_path] = world_data

    for path, value in changed_world.items():
        _write_json(path, value)
    _write_json(DATA / "战斗方向.json", directions)
    _remove_enemy_static_loadouts()
    print(f"generated directions={direction_index} techniques={direction_index * 9} enchantments={direction_index * 9} gems={direction_index * 9}")


if __name__ == "__main__":
    generate()
