"""只加载战斗基石，不加载功法、宝石等二次对象。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from game.core import JsonDataReader

from .executors import EXECUTOR_CATEGORIES
from .schema import RuleSchemaValidator


DEFINITION_PATHS = {
    "属性": "定义/战斗/属性.json",
    "资源": "定义/战斗/资源.json",
    "事件": "定义/战斗/事件.json",
    "原子能力": "定义/战斗/原子能力.json",
}
RULE_PATHS = {
    "伤害规则": "规则/战斗/伤害.json",
    "行动规则": "规则/战斗/行动.json",
    "状态反应": "规则/战斗/状态反应.json",
}


def load_battle_foundation(
    data_root: str | Path,
    *,
    mechanisms: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    reader = JsonDataReader(data_root)
    result = {name: reader.read(path) for name, path in DEFINITION_PATHS.items()}
    result.update({name: reader.read(path) for name, path in RULE_PATHS.items()})
    result["机制"] = {str(key): dict(value) for key, value in (mechanisms or {}).items()}
    validate_battle_foundation(result)
    return result


def validate_battle_foundation(value: Mapping[str, Any]) -> None:
    abilities = _mapping(value.get("原子能力"), "原子能力")
    events = _mapping(value.get("事件"), "事件")
    attributes = _mapping(value.get("属性"), "属性")
    resources = _mapping(value.get("资源"), "资源")
    mechanisms = _mapping(value.get("机制") or {}, "机制")
    action_rules = _mapping(value.get("行动规则"), "行动规则")
    damage_rules = _mapping(value.get("伤害规则"), "伤害规则")
    status_reactions = value.get("状态反应")
    _validate_action_rules(action_rules, attributes, resources)
    _validate_damage_rules(damage_rules)
    for name, raw in events.items():
        definition = _mapping(raw, f"事件.{name}")
        unknown = set(definition) - {"携带事实", "可修改"}
        if unknown:
            raise ValueError(f"事件.{name}存在未知字段：{'、'.join(sorted(unknown))}")
        facts = _strings(definition.get("携带事实"), f"事件.{name}.携带事实")
        mutable = _strings(definition.get("可修改"), f"事件.{name}.可修改")
        if not set(mutable) <= {"当前数值", "目标", "标签", "取消", "类型"}:
            raise ValueError(f"事件.{name}.可修改包含核心不认识的操作")
        if len(facts) != len(set(facts)) or len(mutable) != len(set(mutable)):
            raise ValueError(f"事件.{name}的事实或修改项不能重复")
        if "类型" in mutable and name not in {"恢复前", "获得护盾前", "资源恢复前"}:
            raise ValueError(f"事件.{name}没有可转化的共同结算语义")
    validator = RuleSchemaValidator(
        abilities=abilities,
        executor_categories=EXECUTOR_CATEGORIES,
        attributes=attributes,
        resources=resources,
        events=events,
        mechanisms=mechanisms,
    )
    validator.validate_definitions("定义/战斗/原子能力.json")
    _validate_status_reactions(status_reactions, validator)
    declared = {str(definition.get("执行器") or "") for definition in abilities.values()}
    missing = set(EXECUTOR_CATEGORIES) - declared
    if missing:
        raise ValueError(f"执行器没有原子能力声明：{'、'.join(sorted(missing))}")


def _validate_action_rules(
    value: Mapping[str, Any],
    attributes: Mapping[str, Any],
    resources: Mapping[str, Any],
) -> None:
    expected = {
        "标准速度", "最低有效速度", "最高行动效率", "技能冷却", "每次主行动最多追加攻击",
        "事件链深度上限", "能力链深度上限", "触发技能嵌套上限", "每方召唤物上限",
        "战斗构造物上限", "行动开始恢复",
    }
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        details = []
        if unknown:
            details.append("未知字段 " + "、".join(sorted(unknown)))
        if missing:
            details.append("缺少字段 " + "、".join(sorted(missing)))
        raise ValueError("行动规则" + "；".join(details))
    for name in ("标准速度", "最低有效速度", "最高行动效率"):
        _positive_number(value[name], f"行动规则.{name}")
    for name in (
        "每次主行动最多追加攻击", "事件链深度上限", "能力链深度上限",
        "触发技能嵌套上限", "每方召唤物上限", "战斗构造物上限",
    ):
        if isinstance(value[name], bool) or not isinstance(value[name], int) or value[name] <= 0:
            raise ValueError(f"行动规则.{name}必须是正整数")
    cooldown = _mapping(value["技能冷却"], "行动规则.技能冷却")
    expected_cooldown = {"单位": "自身行动", "推进时点": "行动开始、技能选择前", "每次推进": 1, "缩减取整": "向上取整"}
    if cooldown != expected_cooldown:
        raise ValueError("行动规则.技能冷却必须明确使用自身行动推进")
    recovery = _mapping(value["行动开始恢复"], "行动规则.行动开始恢复")
    for resource, attribute in recovery.items():
        if resource not in resources:
            raise ValueError(f"行动规则.行动开始恢复引用未知资源：{resource}")
        if attribute not in attributes:
            raise ValueError(f"行动规则.行动开始恢复引用未知属性：{attribute}")


def _validate_damage_rules(value: Mapping[str, Any]) -> None:
    expected = {
        "基础命中率", "最低命中率", "最高命中率", "最高暴击倍率", "最高格挡率",
        "最高伤害倍率", "防御常数", "最低伤害",
    }
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        raise ValueError(
            "伤害规则字段不完整："
            + ("未知 " + "、".join(sorted(unknown)) if unknown else "")
            + ("；" if unknown and missing else "")
            + ("缺少 " + "、".join(sorted(missing)) if missing else "")
        )
    for name, number in value.items():
        _positive_number(number, f"伤害规则.{name}", allow_zero=name != "防御常数")
    if not value["最低命中率"] <= value["基础命中率"] <= value["最高命中率"]:
        raise ValueError("伤害规则命中率必须满足最低值 <= 基础值 <= 最高值")


def _validate_status_reactions(value: Any, validator: RuleSchemaValidator) -> None:
    if not isinstance(value, list):
        raise ValueError("状态反应必须是数组")
    names: set[str] = set()
    for index, raw in enumerate(value):
        reaction = _mapping(raw, f"状态反应[{index}]")
        unknown = set(reaction) - {"名称", "需要状态", "消耗层数", "生成状态", "效果"}
        if unknown:
            raise ValueError(f"状态反应[{index}]存在未知字段：{'、'.join(sorted(unknown))}")
        name = str(reaction.get("名称") or "").strip()
        if not name or name in names:
            raise ValueError(f"状态反应[{index}].名称必须非空且不可重复")
        names.add(name)
        required = _strings(reaction.get("需要状态"), f"状态反应[{index}].需要状态")
        if len(required) < 2 or len(required) != len(set(required)):
            raise ValueError(f"状态反应[{index}].需要状态至少两项且不可重复")
        consume = reaction.get("消耗层数", 1)
        if isinstance(consume, bool) or not isinstance(consume, int) or consume < 0:
            raise ValueError(f"状态反应[{index}].消耗层数必须是非负整数")
        generated = reaction.get("生成状态")
        if generated is not None:
            status = _mapping(generated, f"状态反应[{index}].生成状态")
            if not str(status.get("名称") or "").strip():
                raise ValueError(f"状态反应[{index}].生成状态必须有名称")
            validator.validate_node(
                {
                    "能力": "添加状态",
                    "目标": {"能力": "选择目标", "范围": "自身"},
                    "状态": dict(status),
                },
                f"状态反应[{index}].生成状态",
            )
        effects = reaction.get("效果", [])
        if not isinstance(effects, list):
            raise ValueError(f"状态反应[{index}].效果必须是数组")
        for effect_index, effect in enumerate(effects):
            validator.validate_node(effect, f"状态反应[{index}].效果[{effect_index}]")


def _positive_number(value: Any, path: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{path}必须是数字")
    result = float(value)
    if result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"{path}必须{'非负' if allow_zero else '大于零'}")
    return result


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path}必须是对象")
    return value


def _strings(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{path}必须是非空字符串数组")
    return tuple(value)


__all__ = ["load_battle_foundation", "validate_battle_foundation"]
