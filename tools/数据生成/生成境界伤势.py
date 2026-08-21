"""生成正式长期伤势实体；运行时只读取生成后的 JSON。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "data" / "内容" / "角色" / "伤势.json"

REALMS = (
    (
        "510001",
        "灵动",
        ("灵息浮游", "纳气失序", "息走岔脉", "灵窍滞塞", "灵感过炽", "周身散气"),
        "行动结束",
        "来源",
    ),
    (
        "510002",
        "炼气",
        ("气海虚浮", "真气逆冲", "吐纳失衡", "气关闭锁", "丹田鼓荡", "驭气失度"),
        "资源消耗后",
        "来源",
    ),
    (
        "510003",
        "开脉",
        ("经络刺痛", "脉门自锁", "支脉淤结", "气血冲脉", "经络错行", "百脉鸣颤"),
        "技能施放后",
        "来源",
    ),
    (
        "510004",
        "周天",
        ("周天逆滞", "小周天断续", "气机脱环", "内息回冲", "周天争流", "运转失序"),
        "技能冷却变化后",
        "来源",
    ),
    (
        "510005",
        "筑基",
        ("道基裂痕", "基台浮动", "根骨失承", "真元漏泄", "道基偏斜", "筑基余震"),
        "受到伤害后",
        "承受者",
    ),
    (
        "510006",
        "灵海",
        ("灵海干涸", "灵潮倒卷", "海眼闭塞", "真元浑浊", "灵海决堤", "潮息失律"),
        "资源变化后",
        "承受者",
    ),
    (
        "510007",
        "神藏",
        ("神藏闭塞", "藏门失守", "精元外泄", "血肉拒灵", "五藏争鸣", "神藏空鸣"),
        "恢复后",
        "承受者",
    ),
    (
        "510008",
        "灵台",
        ("灵台蒙尘", "识光溃散", "心念滞涩", "灵觉错照", "台火偏燃", "神识回震"),
        "命中后",
        "来源",
    ),
    (
        "510009",
        "紫府",
        ("紫府震荡", "府门错启", "神念滞留", "紫气逆流", "识海侵鸣", "元神失居"),
        "护盾破碎后",
        "承受者",
    ),
    (
        "510010",
        "金丹",
        ("丹火反噬", "金性黯淡", "丹纹裂隙", "真元冲丹", "丹气失衡", "抱元过紧"),
        "状态层数变化后",
        "承受者",
    ),
    (
        "510011",
        "元婴",
        ("婴魄不稳", "元婴离位", "婴息逆行", "灵胎受惊", "婴火失守", "本命牵痛"),
        "复活后",
        "承受者",
    ),
    (
        "510012",
        "婴变",
        ("变相失衡", "形神错契", "婴变滞涩", "灵胎蜕伤", "法相余痕", "本相难归"),
        "形态切换后",
        "承受者",
    ),
    (
        "510013",
        "化神",
        ("神念过载", "法意反冲", "灵机噪鸣", "化神失摄", "神念分岔", "法念灼魂"),
        "技能施放后",
        "来源",
    ),
    (
        "510014",
        "出窍",
        ("离魂迟返", "神魂失锚", "游神染煞", "空壳受创", "归窍错位", "魂息断续"),
        "技能施放失败后",
        "来源",
    ),
    (
        "510015",
        "分神",
        ("分念错序", "主念衰弱", "副念反噬", "神识争权", "万念同噪", "分神难合"),
        "行动跳过后",
        "来源",
    ),
    (
        "510016",
        "洞玄",
        ("玄关反噬", "道理冲突", "玄感过载", "天机刺识", "法则误读", "玄门回锁"),
        "恢复前",
        "承受者",
    ),
    (
        "510017",
        "炼虚",
        ("虚实错位", "法身虚耗", "真形淡薄", "虚空侵痕", "实相不稳", "炼虚回蚀"),
        "闪避后",
        "来源",
    ),
    (
        "510018",
        "合体",
        ("形神不合", "法身排斥", "三元失衡", "合体裂隙", "元神挤压", "肉身滞后"),
        "添加状态后",
        "承受者",
    ),
    (
        "510019",
        "大乘",
        ("万法相冲", "道果震颤", "法域回压", "天地排斥", "圆融有缺", "道统噬主"),
        "状态层数变化后",
        "承受者",
    ),
    (
        "510020",
        "渡劫",
        ("劫痕难消", "雷意残驻", "天威压神", "劫火灼元", "道果劫裂", "生灭失衡"),
        "受到致命伤害",
        "承受者",
    ),
)

EXTERNAL = (
    ("620003", "缄脉", {}, ("技能",), (), {"行动限制任一": ["技能"]}),
    ("620001", "裂创", {"受疗加成": -12}, (), (), {"属性任一": ["受疗加成"]}),
    ("620004", "神裂", {"精神消耗修正": -25}, (), (), {"属性任一": ["精神消耗修正"]}),
    ("620005", "枯井", {"精神恢复": -20}, (), (), {"属性任一": ["精神恢复"]}),
    ("620007", "破格", {"格挡率": -18}, (), (), {"属性任一": ["格挡率"]}),
    ("620008", "失衡", {"命中率": -15}, (), (), {"属性任一": ["命中率"]}),
    (
        "620009",
        "破绽",
        {"闪避率": -8, "伤害减免": -10},
        (),
        (),
        {"属性任一": ["闪避率", "伤害减免"]},
    ),
    ("620010", "冷却债", {"冷却缩减": -20}, (), (), {"属性任一": ["冷却缩减"]}),
    ("620011", "护体裂隙", {"受盾加成": -20}, (), (), {"属性任一": ["受盾加成"]}),
    ("620012", "行动迟滞", {}, (), ("601602",), {"属性任一": ["速度"]}),
    (
        "620006",
        "层裂",
        {"防御": -6, "格挡减伤": -4},
        (),
        (),
        {"属性任一": ["防御", "格挡减伤"]},
    ),
    ("620002", "蚀脉", {}, (), ("601601",), {"兜底": True}),
)


def status(
    attributes: dict[str, int],
    action_limits: tuple[str, ...] = (),
    mechanisms: tuple[str, ...] = (),
    *,
    actions: int = 3,
) -> dict[str, object]:
    return {
        "类别": "负面",
        "剩余行动": actions,
        "持续单位": "状态承受者行动",
        "属性": attributes,
        "行动限制": list(action_limits),
        "标签": ["长期伤势"],
        "机制": list(mechanisms),
    }


def trigger(
    slot: int, special_event: str, special_role: str, tier: int
) -> dict[str, object]:
    if slot == 1:
        return {"类型": "资源归零", "资源": "血气"}
    if slot == 2:
        return {"类型": "资源归零", "资源": "精神"}
    if slot == 3:
        return {"类型": "事件累计", "事件": "受到致命伤害", "角色": "承受者", "次数": 1}
    if slot == 4:
        return {
            "类型": "事件累计",
            "事件": "技能施放失败后",
            "角色": "来源",
            "次数": 1 + tier // 7,
        }
    if slot == 5:
        return {
            "类型": "事件累计",
            "事件": "护盾破碎后",
            "角色": "承受者",
            "次数": 1 + tier // 8,
        }
    return {
        "类型": "事件累计",
        "事件": special_event,
        "角色": special_role,
        "次数": 4 + tier // 3,
    }


def self_status(slot: int, tier: int) -> dict[str, object]:
    step = (tier - 1) // 4
    if slot == 1:
        return status({"受疗加成": -(6 + step * 2), "伤害减免": -(2 + step)})
    if slot == 2:
        return status({"精神恢复": -(6 + step * 3), "精神消耗修正": -(5 + step * 2)})
    if slot == 3:
        return status({"防御": -(2 + step), "格挡减伤": -(2 + step)})
    if slot == 4:
        return status({}, ("技能",), actions=min(3, 1 + tier // 7))
    if slot == 5:
        return status({"受盾加成": -(8 + step * 3), "格挡率": -(3 + step * 2)})
    mechanisms = ("601601",) if tier % 2 == 0 else ("601602",)
    attributes = {"速度": -(3 + step * 2), "命中率": -(2 + step)}
    return status(attributes, mechanisms=mechanisms)


def build() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for priority, (
        injury_id,
        name,
        attributes,
        limits,
        mechanisms,
        matcher,
    ) in enumerate(EXTERNAL, start=1):
        rows.append(
            {
                "编号": injury_id,
                "名称": name,
                "来源类别": "外来伤势",
                "匹配状态": name,
                "匹配优先级": priority,
                "匹配": matcher,
                "战斗状态": status(attributes, limits, mechanisms),
                "叠加": {"层数上限": 3},
                "治疗": {"每层所需轮数": 1, "优先级": 20},
            }
        )
    for tier, (realm_id, realm_name, names, special_event, special_role) in enumerate(
        REALMS, start=1
    ):
        for slot, name in enumerate(names, start=1):
            rows.append(
                {
                    "编号": f"62{tier:02d}{slot:02d}",
                    "名称": name,
                    "来源类别": "境界自生",
                    "境界": realm_id,
                    "触发优先级": slot,
                    "触发": trigger(slot, special_event, special_role, tier),
                    "战斗状态": self_status(slot, tier),
                    "叠加": {"层数上限": 3},
                    "治疗": {
                        "每层所需轮数": 1 + (tier - 1) // 8,
                        "优先级": 30 + slot,
                    },
                    "说明": f"{realm_name}修士自身运转失衡后留下的{name}。",
                }
            )
    return rows


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(build(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    executable = (
        ROOT
        / "node_modules"
        / ".bin"
        / ("prettier.cmd" if os.name == "nt" else "prettier")
    )
    if not executable.is_file():
        raise RuntimeError("缺少项目锁定的 Prettier，无法生成正式 JSON")
    subprocess.run(
        (str(executable), "--write", str(TARGET)),
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
