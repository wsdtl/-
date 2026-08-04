"""生成战场环境实体；每种正式地点地形必须恰好拥有一套环境阶段。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD_ROOT = ROOT / "data" / "内容" / "世界"
OUTPUT_ROOT = ROOT / "data" / "内容" / "战场环境"


# 分组、地形、阶段名、四阶环境语义、承伤阈值。
TERRAINS = (
    ("炎寒", "冰谷", ("冰寂无声", "裂冰鸣谷", "寒棱崩坠", "冰潮封境"), ("寒凝", "回响", "震荡", "寒凝"), (0.32, 0.72, 1.16)),
    ("旷野", "草甸", ("草浪和风", "草根翻土", "尘花乱目", "沃脉裸露"), ("生息", "风扰", "遮蔽", "开阔"), (0.28, 0.68, 1.12)),
    ("旷野", "草原", ("风过长草", "草浪奔涌", "尘幕横野", "旷野无藏"), ("风扰", "牵滞", "遮蔽", "开阔"), (0.28, 0.68, 1.12)),
    ("旷野", "冲积平原", ("泥沙平伏", "水脉泛动", "软土沉陷", "河泥漫野"), ("生息", "水势", "泥陷", "水势"), (0.3, 0.7, 1.15)),
    ("炎寒", "丹崖", ("丹壁蓄热", "赤屑飞迸", "岩火走脉", "丹崖崩红"), ("镇压", "沙蚀", "炽息", "震荡"), (0.34, 0.76, 1.2)),
    ("山岳", "断崖", ("崖台凌空", "碎石惊落", "崖缝横生", "绝壁倾断"), ("风扰", "岩镇", "震荡", "震荡"), (0.38, 0.84, 1.32)),
    ("异境", "风谷", ("谷风回旋", "乱流穿隙", "罡风夺势", "风眼倒卷"), ("风扰", "回响", "风扰", "震荡"), (0.3, 0.68, 1.08)),
    ("林野", "枫林", ("枫阴覆径", "红叶乱目", "枯枝倾折", "残林易燃"), ("遮蔽", "沙蚀", "岩镇", "炽息"), (0.24, 0.58, 0.98)),
    ("山岳", "高地", ("地势抬升", "横风压顶", "土层开裂", "高台崩落"), ("开阔", "风扰", "震荡", "岩镇"), (0.34, 0.78, 1.24)),
    ("炎寒", "高原", ("天高气薄", "寒风削灵", "冻土开裂", "罡寒封原"), ("寒凝", "炽息", "震荡", "寒凝"), (0.36, 0.8, 1.28)),
    ("山岳", "谷地", ("谷气沉积", "回声叠荡", "地气壅塞", "谷底翻涌"), ("生息", "回响", "镇压", "震荡"), (0.32, 0.74, 1.18)),
    ("水泽", "海岸", ("潮风拂岸", "浪沫遮目", "潮线侵进", "怒潮拍岸"), ("风扰", "遮蔽", "水势", "破潮"), (0.28, 0.68, 1.1)),
    ("林野", "寒林", ("寒枝蔽影", "霜叶坠落", "冻木横陈", "冷林尽折"), ("遮蔽", "寒凝", "岩镇", "寒凝"), (0.28, 0.64, 1.04)),
    ("水泽", "寒沼", ("冻泥潜伏", "冰壳碎裂", "寒沼噬步", "沼气封息"), ("泥陷", "震荡", "泥陷", "寒凝"), (0.24, 0.58, 0.96)),
    ("水泽", "河堤", ("堤势束流", "渗水松土", "堤脚淘空", "决堤横冲"), ("镇压", "水势", "泥陷", "水势"), (0.34, 0.74, 1.14)),
    ("水泽", "河谷", ("水声沿谷", "湿雾漫行", "急流撞岸", "河谷奔洪"), ("生息", "遮蔽", "水势", "水势"), (0.3, 0.7, 1.12)),
    ("水泽", "河口", ("江海相持", "回潮乱流", "浊浪翻沙", "潮门大开"), ("水势", "破潮", "沙蚀", "水势"), (0.3, 0.68, 1.08)),
    ("水泽", "河湾", ("缓流绕湾", "旋涡聚势", "湾岸坍软", "回流夺步"), ("生息", "水势", "泥陷", "水势"), (0.28, 0.66, 1.08)),
    ("山岳", "黑岩山岭", ("黑岩镇势", "石屑迸飞", "岩脊断层", "山岭倾轧"), ("岩镇", "沙蚀", "震荡", "镇压"), (0.4, 0.88, 1.38)),
    ("水泽", "湖滨", ("湖光平镜", "涟漪叠生", "岸泥松陷", "湖浪越岸"), ("生息", "水势", "泥陷", "破潮"), (0.28, 0.66, 1.08)),
    ("水泽", "湖汊", ("支流潜行", "水道交错", "汊口倒灌", "群流争势"), ("生息", "水势", "破潮", "水势"), (0.28, 0.64, 1.04)),
    ("水泽", "湖湾", ("湾水静蓄", "暗涌回旋", "湖岸剥落", "湾潮扑卷"), ("生息", "水势", "泥陷", "破潮"), (0.3, 0.68, 1.1)),
    ("旷野", "荒丘", ("丘风卷尘", "浮土滑落", "丘脊开裂", "荒丘削平"), ("沙蚀", "牵滞", "震荡", "开阔"), (0.3, 0.7, 1.16)),
    ("炎寒", "火山", ("火脉沉眠", "硫烟逸散", "熔脉喷张", "山腹震爆"), ("炽息", "遮蔽", "炽息", "雷灼"), (0.28, 0.62, 1.0)),
    ("炎寒", "火山坡", ("热土蒸腾", "火石滚落", "熔流横切", "山火倾坡"), ("炽息", "岩镇", "炽息", "水势"), (0.28, 0.64, 1.02)),
    ("水泽", "江岸", ("江风贴岸", "水汽迷目", "岸线崩蚀", "大江拍陆"), ("风扰", "遮蔽", "水势", "破潮"), (0.3, 0.7, 1.12)),
    ("异境", "雷谷", ("余雷游壑", "电光寻隙", "群雷交织", "天雷灌谷"), ("雷灼", "雷灼", "雷灼", "雷灼"), (0.26, 0.58, 0.94)),
    ("异境", "裂隙荒原", ("地缝沉寂", "裂口吐风", "地层错动", "荒原撕裂"), ("镇压", "风扰", "震荡", "震荡"), (0.34, 0.76, 1.18)),
    ("林野", "林地", ("林影深覆", "枝叶惊动", "倒木横陈", "林冠洞开"), ("遮蔽", "风扰", "岩镇", "开阔"), (0.26, 0.62, 1.02)),
    ("水泽", "芦苇湿地", ("苇影藏身", "湿泥牵足", "苇浪倒伏", "泽水漫滩"), ("遮蔽", "泥陷", "风扰", "水势"), (0.24, 0.58, 0.98)),
    ("旷野", "平原", ("地平天阔", "尘迹扬起", "土脉龟裂", "四野无遮"), ("开阔", "沙蚀", "震荡", "开阔"), (0.32, 0.76, 1.2)),
    ("山岳", "丘陵", ("缓丘起伏", "坡土滑移", "丘脊断裂", "群丘塌陷"), ("牵滞", "泥陷", "震荡", "岩镇"), (0.32, 0.74, 1.18)),
    ("水泽", "泉谷", ("泉脉清鸣", "水汽充谷", "泉眼并涌", "谷泉倒灌"), ("生息", "遮蔽", "生息", "水势"), (0.28, 0.66, 1.06)),
    ("炎寒", "熔岩谷", ("熔壑暗红", "热浪灼息", "熔流分岔", "赤潮封谷"), ("炽息", "炽息", "水势", "炽息"), (0.24, 0.56, 0.92)),
    ("旷野", "沙地", ("浮沙浅移", "扬尘遮天", "流沙陷足", "沙暴横卷"), ("牵滞", "遮蔽", "泥陷", "风扰"), (0.24, 0.58, 0.96)),
    ("水泽", "沙洲", ("洲沙平展", "潮水割岸", "沙脊迁移", "孤洲将没"), ("开阔", "水势", "牵滞", "破潮"), (0.26, 0.62, 1.0)),
    ("山岳", "山谷", ("山气收束", "谷声回返", "碎岩塞道", "山谷震鸣"), ("镇压", "回响", "岩镇", "震荡"), (0.34, 0.76, 1.2)),
    ("山岳", "山脊", ("脊风横行", "危岩松动", "山骨开裂", "长脊崩断"), ("风扰", "岩镇", "震荡", "震荡"), (0.36, 0.8, 1.28)),
    ("山岳", "山间盆地", ("四山环抱", "沉气聚拢", "盆缘坍落", "地气反冲"), ("镇压", "生息", "岩镇", "震荡"), (0.36, 0.82, 1.3)),
    ("山岳", "山口", ("两山夹风", "乱流争道", "关隘落石", "山口崩宽"), ("风扰", "风扰", "岩镇", "震荡"), (0.34, 0.76, 1.2)),
    ("山岳", "山麓", ("山根安定", "坡石滚散", "地脉抬动", "山脚倾陷"), ("岩镇", "牵滞", "震荡", "泥陷"), (0.36, 0.8, 1.26)),
    ("水泽", "湿地", ("水草潜伏", "泥水混流", "泽面下沉", "湿地泛滥"), ("遮蔽", "泥陷", "泥陷", "水势"), (0.24, 0.58, 0.96)),
    ("山岳", "石岭", ("石骨嶙峋", "碎砾飞散", "岭脉断响", "群石奔落"), ("岩镇", "沙蚀", "震荡", "岩镇"), (0.38, 0.84, 1.32)),
    ("水泽", "水网平原", ("水渠纵横", "支流漫溢", "软土塌沉", "百水并流"), ("水势", "生息", "泥陷", "水势"), (0.28, 0.66, 1.06)),
    ("林野", "松林", ("松影常青", "松针乱坠", "老木折断", "林地敞开"), ("遮蔽", "沙蚀", "岩镇", "开阔"), (0.28, 0.64, 1.04)),
    ("水泽", "温泉谷地", ("暖泉润脉", "蒸雾蔽目", "泉眼沸涌", "热水漫谷"), ("生息", "遮蔽", "炽息", "水势"), (0.26, 0.62, 1.0)),
    ("旷野", "沃野", ("沃土生息", "草浪翻涌", "土层翻裂", "灵田尽乱"), ("生息", "风扰", "震荡", "开阔"), (0.3, 0.72, 1.16)),
    ("水泽", "溪谷", ("溪声清浅", "水雾绕石", "溪流急涨", "山溪冲谷"), ("生息", "遮蔽", "水势", "水势"), (0.28, 0.66, 1.06)),
    ("山岳", "峡谷", ("峡风穿壁", "回声震荡", "危岩坠落", "两壁共鸣"), ("风扰", "回响", "岩镇", "震荡"), (0.36, 0.8, 1.26)),
    ("山岳", "岩地", ("岩面坚稳", "石片崩飞", "岩层错裂", "地盘震荡"), ("岩镇", "沙蚀", "震荡", "镇压"), (0.38, 0.84, 1.32)),
    ("旷野", "原野", ("野风舒展", "草尘纷起", "地表开裂", "天无遮拦"), ("风扰", "沙蚀", "震荡", "开阔"), (0.3, 0.72, 1.16)),
    ("异境", "云岭", ("云气缠岭", "云流遮目", "罡风撕云", "岭顶天开"), ("遮蔽", "遮蔽", "风扰", "开阔"), (0.3, 0.68, 1.08)),
    ("异境", "云雾山地", ("雾锁群峰", "湿云压身", "云雷暗生", "山雾翻海"), ("遮蔽", "泥陷", "雷灼", "风扰"), (0.28, 0.64, 1.02)),
    ("林野", "竹林", ("竹影摇风", "竹叶啸响", "折竹横生", "竹海倾伏"), ("遮蔽", "回响", "岩镇", "风扰"), (0.24, 0.58, 0.98)),
)


# 每种地势明确拥有自己的三段收束路线，不从地理大类继承通用模板。
TERRAIN_PRESSURES = {
    "冰谷": ("寒滞", "冰裂", "冰封"),
    "草甸": ("风痕", "锁定", "草根翻涌"),
    "草原": ("风痕", "沙蚀", "追风"),
    "冲积平原": ("潮滞", "泥陷", "决堤"),
    "丹崖": ("沙蚀", "灼脉", "震岩"),
    "断崖": ("风痕", "断守", "震岩"),
    "风谷": ("风眼", "乱法", "追风"),
    "枫林": ("雾锁", "破隐", "焚林"),
    "高地": ("锁定", "断守", "震岩"),
    "高原": ("寒滞", "耗神", "风眼"),
    "谷地": ("回响", "镇盾", "地涌"),
    "海岸": ("风痕", "潮滞", "怒潮"),
    "寒林": ("雾锁", "寒滞", "冰封"),
    "寒沼": ("泥陷", "寒滞", "沼封"),
    "河堤": ("潮滞", "蚀盾", "决堤"),
    "河谷": ("雾锁", "漩涡", "封疗"),
    "河口": ("乱法", "蚀盾", "决堤"),
    "河湾": ("潮滞", "漩涡", "封疗"),
    "黑岩山岭": ("镇盾", "断守", "震岩"),
    "湖滨": ("雾锁", "漩涡", "湖浪"),
    "湖汊": ("乱法", "漩涡", "决堤"),
    "湖湾": ("雾锁", "潮滞", "决堤"),
    "荒丘": ("沙蚀", "泥陷", "锁定"),
    "火山": ("耗神", "灼脉", "火狱"),
    "火山坡": ("震岩", "流火", "火狱"),
    "江岸": ("风痕", "潮滞", "江崩"),
    "雷谷": ("雷感", "雷击", "雷狱"),
    "裂隙荒原": ("乱法", "空裂", "裂界"),
    "林地": ("雾锁", "破隐", "断守"),
    "芦苇湿地": ("雾锁", "泥陷", "决堤"),
    "平原": ("锁定", "追风", "封疗"),
    "丘陵": ("泥陷", "断守", "震岩"),
    "泉谷": ("生机逆涌", "潮滞", "封疗"),
    "熔岩谷": ("灼脉", "流火", "火狱"),
    "沙地": ("沙蚀", "泥陷", "沙暴"),
    "沙洲": ("锁定", "潮滞", "决堤"),
    "山谷": ("回响", "断守", "震岩"),
    "山脊": ("风痕", "崩格", "震岩"),
    "山间盆地": ("镇盾", "蚀盾", "地涌"),
    "山口": ("风眼", "崩格", "震岩"),
    "山麓": ("泥陷", "断守", "地涌"),
    "湿地": ("雾锁", "泥陷", "沼封"),
    "石岭": ("沙蚀", "断守", "震岩"),
    "水网平原": ("潮滞", "漩涡", "决堤"),
    "松林": ("雾锁", "破隐", "松脂火"),
    "温泉谷地": ("雾锁", "耗神", "沸泉"),
    "沃野": ("生机逆涌", "锁定", "封疗"),
    "溪谷": ("雾锁", "漩涡", "山洪"),
    "峡谷": ("回响", "崩格", "震岩"),
    "岩地": ("镇盾", "断守", "地涌"),
    "原野": ("风痕", "锁定", "追风"),
    "云岭": ("雾锁", "风眼", "锁定"),
    "云雾山地": ("雾锁", "雷感", "雷击"),
    "竹林": ("回响", "破隐", "断守"),
}


def target(scope: str, *, all_targets: bool = False) -> dict[str, Any]:
    value: dict[str, Any] = {"能力": "选择目标", "范围": scope}
    if all_targets:
        value["选择全部"] = True
    return value


def probability(value: int) -> dict[str, Any]:
    return {"能力": "概率条件", "概率": value}


def status_effect(
    name: str,
    modifiers: dict[str, float],
    *,
    turns: int = 2,
    category: str = "中性",
) -> dict[str, Any]:
    return {
        "能力": "添加状态",
        "目标": target("全体", all_targets=True),
        "状态": {
            "名称": name,
            "类别": category,
            "剩余行动": turns,
            "重复方式": "刷新持续",
            "属性": modifiers,
            "标签": ["战场环境"],
        },
    }


def entry_effect(profile: str, stage_name: str, intensity: int) -> list[dict[str, Any]]:
    if profile == "遮蔽":
        return [status_effect(stage_name, {"命中率": -2 * intensity})]
    if profile == "开阔":
        return [status_effect(stage_name, {"命中率": 2 * intensity, "闪避率": -intensity})]
    if profile in {"牵滞", "泥陷"}:
        return [status_effect(stage_name, {"速度": -3 * intensity})]
    if profile == "寒凝":
        return [
            status_effect(
                stage_name,
                {"速度": -2 * intensity, "冷却缩减": -2 * intensity},
            )
        ]
    if profile == "生息":
        return [status_effect(stage_name, {"治疗加成": 2 * intensity})]
    if profile in {"岩镇", "镇压"}:
        return [status_effect(stage_name, {"防御": 2 * intensity})]
    if profile in {"风扰", "回响", "水势", "破潮"}:
        return [
            {
                "能力": "修改行动条",
                "目标": target("全体", all_targets=True),
                "方式": "减少",
                "数值": 2 + intensity,
            }
        ]
    if profile in {"震荡", "沙蚀"}:
        return [status_effect(stage_name, {"格挡率": -intensity, "闪避率": -intensity})]
    if profile == "炽息":
        return [status_effect(stage_name, {"精神消耗修正": -3 * intensity})]
    if profile == "雷灼":
        return [status_effect(stage_name, {"冷却缩减": -3 * intensity})]
    raise ValueError(f"未知环境语义：{profile}")


def listener(profile: str, stage_name: str, intensity: int) -> dict[str, Any]:
    base: dict[str, Any] = {
        "能力": "监听事件",
        "观察角色": "来源",
        "阵营关系": "任意",
        "每次行动最多触发": 1,
    }
    if profile in {"遮蔽", "开阔"}:
        base.update(
            {
                "事件": "命中判定前",
                "条件": [probability(4 + intensity * 2)],
                "效果": [
                    {
                        "能力": "修改判定",
                        "判定": "命中",
                        "方式": "必定失败" if profile == "遮蔽" else "必定成功",
                        "次数": 1,
                    }
                ],
            }
        )
    elif profile in {"牵滞", "泥陷", "风扰"}:
        base.update(
            {
                "事件": "行动结束",
                "观察角色": "行动者",
                "效果": [
                    {
                        "能力": "修改行动条",
                        "目标": target("事件来源"),
                        "方式": "减少",
                        "数值": 2 + intensity * 2,
                    }
                ],
            }
        )
    elif profile == "生息":
        base.update(
            {
                "事件": "恢复后",
                "观察角色": "承受者",
                "效果": [
                    {
                        "能力": "修改行动条",
                        "目标": target("事件承受者"),
                        "方式": "增加",
                        "数值": 1 + intensity,
                    }
                ],
            }
        )
    elif profile == "岩镇":
        base.update(
            {
                "事件": "格挡后",
                "效果": [
                    {
                        "能力": "修改行动条",
                        "目标": target("事件来源"),
                        "方式": "减少",
                        "数值": 3 + intensity * 2,
                    }
                ],
            }
        )
    elif profile == "震荡":
        base.update(
            {
                "事件": "暴击后",
                "效果": [
                    {
                        "能力": "修改行动条",
                        "目标": target("事件来源"),
                        "方式": "减少",
                        "数值": 2 + intensity,
                    },
                    {
                        "能力": "修改行动条",
                        "目标": target("事件承受者"),
                        "方式": "减少",
                        "数值": 3 + intensity,
                    },
                ],
            }
        )
    elif profile == "炽息":
        base.update(
            {
                "事件": "技能施放后",
                "效果": [
                    {
                        "能力": "消耗资源",
                        "目标": target("事件来源"),
                        "资源": "精神",
                        "数值": {
                            "能力": "读取数值",
                            "来源": "目标属性",
                            "目标": target("事件来源"),
                            "属性": "精神上限",
                            "百分比": 1 + intensity,
                        },
                        "不足时是否失败": False,
                    }
                ],
            }
        )
    elif profile in {"寒凝", "回响"}:
        base.update(
            {
                "事件": "技能施放后",
                "条件": [probability(7 + intensity * 3)],
                "效果": [
                    {
                        "能力": "修改技能冷却",
                        "目标": target("事件来源"),
                        "技能": {
                            "能力": "选择技能",
                            "范围": "冷却中的技能",
                            "排序": "冷却从高到低",
                        },
                        "方式": "增加",
                        "数值": 1,
                    }
                ],
            }
        )
    elif profile == "雷灼":
        base.update(
            {
                "事件": "技能施放后",
                "条件": [probability(6 + intensity * 3)],
                "效果": [
                    {
                        "能力": "造成伤害",
                        "名称": stage_name,
                        "目标": target("事件来源"),
                        "数值": {
                            "能力": "读取数值",
                            "来源": "目标属性",
                            "目标": target("事件来源"),
                            "属性": "血气上限",
                            "百分比": 1 + intensity,
                        },
                        "防御规则": "真实",
                        "能否暴击": False,
                        "能否格挡": False,
                        "标签": ["环境伤害"],
                    }
                ],
            }
        )
    elif profile == "沙蚀":
        base.update(
            {
                "事件": "造成伤害后",
                "效果": [
                    {
                        "能力": "添加状态",
                        "目标": target("事件来源"),
                        "状态": {
                            "名称": stage_name,
                            "类别": "负面",
                            "剩余行动": 2,
                            "重复方式": "刷新持续",
                            "属性": {"命中率": -intensity},
                            "标签": ["战场环境"],
                        },
                    }
                ],
            }
        )
    elif profile in {"水势", "破潮"}:
        base.update(
            {
                "事件": "护盾破碎后" if profile == "破潮" else "受到伤害后",
                "观察角色": "承受者",
                "效果": [
                    {
                        "能力": "修改行动条",
                        "目标": target("事件承受者"),
                        "方式": "减少",
                        "数值": 2 + intensity * 2,
                    }
                ],
            }
        )
    elif profile == "镇压":
        base.update(
            {
                "事件": "获得护盾前",
                "观察角色": "承受者",
                "效果": [
                    {
                        "能力": "修改事件数值",
                        "方式": "乘算",
                        "数值": 100 - intensity * 4,
                    }
                ],
            }
        )
    else:
        raise ValueError(f"未知环境语义：{profile}")
    return base


def percent_damage(name: str, scope: str, percent: int) -> dict[str, Any]:
    return {
        "能力": "造成伤害",
        "名称": name,
        "目标": target(scope, all_targets=scope == "全体"),
        "数值": {
            "能力": "读取数值",
            "来源": "目标属性",
            "目标": target("当前目标" if scope == "全体" else scope),
            "属性": "血气上限",
            "百分比": percent,
        },
        "防御规则": "真实",
        "能否暴击": False,
        "能否格挡": False,
        "标签": ["环境伤害"],
    }


def event_listener(
    event: str,
    effects: list[dict[str, Any]],
    *,
    role: str = "来源",
    chance: int | None = None,
    per_action: int = 1,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "能力": "监听事件",
        "事件": event,
        "观察角色": role,
        "阵营关系": "任意",
        "效果": effects,
        "每次行动最多触发": per_action,
    }
    if chance is not None:
        value["条件"] = [probability(chance)]
    return value


def event_multiplier(event: str, value: int, *, role: str = "承受者") -> dict[str, Any]:
    return event_listener(
        event,
        [{"能力": "修改事件数值", "方式": "乘算", "数值": value}],
        role=role,
        per_action=3,
    )


def exposed_status(name: str, scope: str, modifiers: dict[str, float]) -> dict[str, Any]:
    return {
        "能力": "添加状态",
        "目标": target(scope),
        "状态": {
            "名称": name,
            "类别": "负面",
            "剩余行动": 2,
            "重复方式": "刷新持续",
            "属性": modifiers,
            "标签": ["战场环境"],
        },
    }


def cooldown_effect(scope: str, mode: str, value: int) -> dict[str, Any]:
    return {
        "能力": "修改技能冷却",
        "目标": target(scope),
        "技能": {
            "能力": "选择技能",
            "范围": "冷却中的技能",
            "排序": "冷却从高到低",
        },
        "方式": mode,
        "数值": value,
    }


def action_bar_effect(scope: str, mode: str, value: int) -> dict[str, Any]:
    return {
        "能力": "修改行动条",
        "目标": target(scope),
        "方式": mode,
        "数值": value,
    }


def spirit_drain(percent: int) -> dict[str, Any]:
    return {
        "能力": "消耗资源",
        "目标": target("事件来源"),
        "资源": "精神",
        "数值": {
            "能力": "读取数值",
            "来源": "目标属性",
            "目标": target("事件来源"),
            "属性": "精神上限",
            "百分比": percent,
        },
        "不足时是否失败": False,
    }


def terrain_pressure(kind: str, stage_name: str, intensity: int) -> list[dict[str, Any]]:
    if kind == "破隐":
        return [event_listener("闪避后", [exposed_status(stage_name, "事件承受者", {"闪避率": -6 - intensity, "防御": -2 * intensity})], role="承受者")]
    if kind == "断守":
        return [event_listener("格挡后", [exposed_status(stage_name, "事件承受者", {"格挡率": -5 - intensity, "格挡减伤": -3 * intensity})], role="承受者")]
    if kind == "封疗":
        return [event_multiplier("恢复前", max(42, 82 - intensity * 10))]
    if kind in {"蚀盾", "镇盾"}:
        multiplier = 48 if kind == "蚀盾" else 65
        return [event_multiplier("获得护盾前", multiplier)]
    if kind == "决堤":
        return [
            event_multiplier("恢复前", 35),
            event_listener("护盾破碎后", [percent_damage(stage_name, "事件承受者", 4), action_bar_effect("事件承受者", "减少", 14)], role="承受者"),
        ]
    if kind in {"怒潮", "江崩", "湖浪", "山洪"}:
        recovery = {"怒潮": 42, "江崩": 48, "湖浪": 55, "山洪": 35}[kind]
        damage = {"怒潮": 5, "江崩": 4, "湖浪": 3, "山洪": 4}[kind]
        extra = (
            exposed_status(stage_name, "事件承受者", {"防御": -6})
            if kind == "江崩"
            else action_bar_effect("事件承受者", "减少", 10 + damage)
        )
        return [
            event_multiplier("恢复前", recovery),
            event_listener("护盾破碎后", [percent_damage(stage_name, "事件承受者", damage), extra], role="承受者"),
        ]
    if kind in {"震岩", "地涌"}:
        event = "暴击后" if kind == "震岩" else "格挡后"
        return [event_listener(event, [percent_damage(stage_name, "事件来源", 2 + intensity)], chance=24 + intensity * 4)]
    if kind == "锁定":
        return [event_listener("命中判定前", [{"能力": "修改判定", "判定": "命中", "方式": "重掷取优", "次数": 1}], chance=18 + intensity * 4)]
    if kind == "崩格":
        return [event_listener("格挡判定前", [{"能力": "修改判定", "判定": "格挡", "方式": "必定失败", "次数": 1}], chance=20 + intensity * 4)]
    if kind == "追风":
        return [event_listener("暴击后", [action_bar_effect("事件来源", "增加", 12 + intensity * 2), cooldown_effect("事件来源", "减少", 1)])]
    if kind == "风痕":
        return [event_listener("行动结束", [action_bar_effect("事件来源", "减少", 4 + intensity * 2)], role="行动者")]
    if kind == "耗神":
        return [event_listener("技能施放后", [spirit_drain(3 + intensity)])]
    if kind in {"寒滞", "回响", "雷感"}:
        chance = {"寒滞": 24, "回响": 30, "雷感": 36}[kind]
        return [event_listener("技能施放后", [cooldown_effect("事件来源", "增加", 1)], chance=chance)]
    if kind == "乱法":
        return [event_listener("技能施放后", [{"能力": "随机执行", "抽取数量": 1, "是否放回": False, "选项": [cooldown_effect("事件来源", "清空", 0), cooldown_effect("事件来源", "增加", 2)]}], chance=28 + intensity * 2)]
    if kind in {"灼脉", "焚林", "沸泉"}:
        return [event_listener("技能施放后", [percent_damage(stage_name, "事件来源", 2 + intensity)], chance=24 + intensity * 3)]
    if kind == "松脂火":
        return [event_listener("技能施放后", [percent_damage(stage_name, "事件来源", 4)], chance=38)]
    if kind in {"火狱", "雷击", "雷狱"}:
        damage = 4 if kind == "雷击" else 6
        effects = [percent_damage(stage_name, "事件来源", damage)]
        if kind == "雷狱":
            effects.append(cooldown_effect("事件来源", "增加", 1))
        return [event_listener("技能施放后", effects, chance=32 + intensity * 2)]
    if kind in {"流火", "空裂", "裂界"}:
        damage = {"流火": 4, "空裂": 3, "裂界": 6}[kind]
        return [event_listener("行动结束", [percent_damage(stage_name, "事件来源", damage)], role="行动者", chance=26 + intensity * 3)]
    if kind == "泥陷":
        return [event_listener("行动结束", [action_bar_effect("事件来源", "减少", 7 + intensity * 2), exposed_status(stage_name, "事件来源", {"速度": -2 * intensity})], role="行动者")]
    if kind == "潮滞":
        return [event_listener("恢复后", [action_bar_effect("事件承受者", "减少", 6 + intensity * 2)], role="承受者")]
    if kind == "漩涡":
        return [event_listener("受到伤害后", [action_bar_effect("事件承受者", "减少", 5 + intensity * 2)], role="承受者")]
    if kind == "沙蚀":
        return [event_listener("造成伤害后", [exposed_status(stage_name, "事件来源", {"命中率": -2 * intensity, "格挡率": -intensity})])]
    if kind in {"雾锁", "沙暴"}:
        failure = 12 + intensity * (4 if kind == "沙暴" else 3)
        return [event_listener("命中判定前", [{"能力": "修改判定", "判定": "命中", "方式": "必定失败", "次数": 1}], chance=failure)]
    if kind == "风眼":
        return [event_listener("行动结束", [{"能力": "随机执行", "抽取数量": 1, "是否放回": False, "选项": [action_bar_effect("事件来源", "增加", 12), action_bar_effect("事件来源", "减少", 12)]}], role="行动者")]
    if kind in {"冰裂", "冰封"}:
        event = "技能冷却完成后" if kind == "冰裂" else "技能施放后"
        effects = [percent_damage(stage_name, "事件来源", 3)] if kind == "冰裂" else [exposed_status(stage_name, "事件来源", {"速度": -8, "受疗加成": -15})]
        return [event_listener(event, effects, chance=30 + intensity * 2)]
    if kind == "沼封":
        return [event_multiplier("恢复前", 48), event_listener("恢复后", [exposed_status(stage_name, "事件承受者", {"速度": -8})], role="承受者")]
    if kind == "生机逆涌":
        return [event_listener("恢复后", [exposed_status(stage_name, "事件承受者", {"受疗加成": -6 * intensity})], role="承受者")]
    if kind == "草根翻涌":
        return [event_listener("恢复后", [exposed_status(stage_name, "事件承受者", {"防御": -6, "受疗加成": -18})], role="承受者")]
    raise ValueError(f"未实现的地势压力：{kind}")


def environment(identity: str, terrain: tuple[Any, ...]) -> tuple[str, dict[str, Any]]:
    group, name, stage_names, profiles, thresholds = terrain
    pressures = TERRAIN_PRESSURES[name]
    starts = (0.0, *thresholds)
    stages = []
    for index, (stage_name, profile, start) in enumerate(zip(stage_names, profiles, starts, strict=True)):
        intensity = index + 1
        stages.append(
            {
                "名称": stage_name,
                "起始承伤比例": start,
                "入阶能力": [
                    *([] if index == 0 else entry_effect(profile, stage_name, intensity)),
                ],
                "常驻能力": [
                    listener(profile, stage_name, intensity),
                    *(
                        []
                        if index == 0
                        else terrain_pressure(
                            pressures[index - 1], stage_name, intensity
                        )
                    ),
                ],
            }
        )
    return group, {"编号": identity, "名称": name, "阶段": stages}


def location_terrains() -> set[str]:
    result: set[str] = set()
    for path in WORLD_ROOT.rglob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and "坐标" in value:
            result.add(str(value["地形"]))
    return result


def main() -> None:
    declared = {str(row[1]) for row in TERRAINS}
    actual = location_terrains()
    if declared != actual:
        missing = "、".join(sorted(actual - declared)) or "无"
        extra = "、".join(sorted(declared - actual)) or "无"
        raise RuntimeError(f"战场环境没有完整覆盖地点地形：缺少 {missing}；多余 {extra}")
    pressure_terrains = set(TERRAIN_PRESSURES)
    if pressure_terrains != declared:
        missing = "、".join(sorted(declared - pressure_terrains)) or "无"
        extra = "、".join(sorted(pressure_terrains - declared)) or "无"
        raise RuntimeError(f"地势压力路线不完整：缺少 {missing}；多余 {extra}")
    if len(set(TERRAIN_PRESSURES.values())) != len(TERRAIN_PRESSURES):
        raise RuntimeError("不同地势不能复用完全相同的三段压力路线")

    documents: dict[str, list[dict[str, Any]]] = {"无相境": [
        {
            "编号": "610001",
            "名称": "无相境",
            "阶段": [
                {
                    "名称": "寂然无相",
                    "起始承伤比例": 0,
                    "入阶能力": [],
                    "常驻能力": [],
                }
            ],
        }
    ]}
    for serial, terrain in enumerate(TERRAINS, start=2):
        _, value = environment(f"61{serial:04d}", terrain)
        documents[str(value["名称"])] = [value]

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    expected = {f"{name}.json" for name in documents}
    for path in OUTPUT_ROOT.glob("*.json"):
        if path.name not in expected:
            path.unlink()
    for name, values in documents.items():
        (OUTPUT_ROOT / f"{name}.json").write_text(
            json.dumps(values, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
