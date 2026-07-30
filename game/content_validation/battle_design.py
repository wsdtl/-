"""战斗方向、三类资源和长期平衡规则的统一校验。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from game.rules.loadout import KINDS, has_compatible_loadout


META_FIELDS = ("提供标签", "需要标签", "禁止标签", "互斥组")
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


def validate_battle_design(
    *,
    combination: Mapping[str, Any],
    balance: Mapping[str, Any],
    grades: Mapping[str, Any],
    directions: Mapping[str, Mapping[str, Any]],
    group_directions: Mapping[str, Mapping[str, str]],
    groups: Mapping[str, Mapping[str, Sequence[str]]],
    definitions: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> None:
    _validate_global_rules(combination, balance, grades)
    _validate_resource_metadata(definitions)
    _validate_direction_catalog(
        combination=combination,
        balance=balance,
        directions=directions,
        group_directions=group_directions,
        groups=groups,
        definitions=definitions,
    )


def _validate_global_rules(
    combination: Mapping[str, Any],
    balance: Mapping[str, Any],
    grades: Mapping[str, Any],
) -> None:
    expected_directions = _positive_integer(combination.get("方向数量"), "组合规则.方向数量")
    if expected_directions != 264:
        raise ValueError("组合规则.方向数量必须为264")
    minimums = _mapping(combination, "方向候选下限")
    for kind in KINDS:
        if _positive_integer(minimums.get(kind), f"组合规则.方向候选下限.{kind}") < 9:
            raise ValueError(f"组合规则.方向候选下限.{kind}不能低于9")
    slots = tuple(_positive_integer(value, "组合规则.校验槽位") for value in _sequence(combination, "校验槽位"))
    if slots != (3, 6):
        raise ValueError("组合规则.校验槽位必须依次为3、6")
    role_rules = _mapping(combination, "功法职责")
    for slot in slots:
        rule = _mapping(role_rules, str(slot))
        active = _positive_integer(rule.get("主动最少"), f"组合规则.功法职责.{slot}.主动最少")
        passive = _positive_integer(rule.get("被动最少"), f"组合规则.功法职责.{slot}.被动最少")
        if active + passive > slot:
            raise ValueError(f"组合规则.功法职责.{slot}超过槽位数量")
    enemy_loadouts = _mapping(combination, "敌方修士构筑")
    expected_scopes = {"普通": "随机方向", "首领": "全池"}
    for rank, expected_scope in expected_scopes.items():
        rule = _mapping(enemy_loadouts, rank)
        if str(rule.get("候选范围") or "") != expected_scope:
            raise ValueError(
                f"组合规则.敌方修士构筑.{rank}.候选范围必须为{expected_scope}"
            )
        for field in ("功法位", "附魔位", "宝石位"):
            if _positive_integer(
                rule.get(field),
                f"组合规则.敌方修士构筑.{rank}.{field}",
            ) != 6:
                raise ValueError(f"组合规则.敌方修士构筑.{rank}.{field}必须为6")
    theme_limit = _positive_integer(
        _mapping(enemy_loadouts, "首领").get("战术数量上限"),
        "组合规则.敌方修士构筑.首领.战术数量上限",
    )
    if theme_limit > 6:
        raise ValueError("组合规则.敌方修士构筑.首领.战术数量上限不能大于6")
    if _positive_integer(combination.get("生成尝试上限"), "组合规则.生成尝试上限") < 10:
        raise ValueError("组合规则.生成尝试上限不能低于10")

    gap = _mapping(balance, "方向差距")
    target = _percentage(gap.get("目标百分比"), "平衡规则.方向差距.目标百分比")
    warning = _percentage(gap.get("预警百分比"), "平衡规则.方向差距.预警百分比")
    rejected = _percentage(gap.get("拒绝百分比"), "平衡规则.方向差距.拒绝百分比")
    if not target < warning <= rejected:
        raise ValueError("平衡规则.方向差距必须满足目标小于预警且预警不高于拒绝线")
    if rejected != 50:
        raise ValueError("平衡规则.方向差距.拒绝百分比必须为50")
    if tuple(_sequence(balance, "测试槽位")) != (3, 6):
        raise ValueError("平衡规则.测试槽位必须依次为3、6")
    if tuple(str(value) for value in _sequence(balance, "测试品级")) != tuple(grades):
        raise ValueError("平衡规则.测试品级必须覆盖全部品级并保持阶序")
    dimensions = _mapping(balance, "评分维度")
    if tuple(dimensions) != DIMENSIONS:
        raise ValueError("平衡规则.评分维度必须使用完整且固定的八个维度")
    if sum(_positive_integer(value, f"平衡规则.评分维度.{key}") for key, value in dimensions.items()) != 100:
        raise ValueError("平衡规则.评分维度权重合计必须为100")


def _validate_resource_metadata(
    definitions: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> None:
    release_orders: dict[int, str] = {}
    settlement_orders: dict[int, str] = {}
    for kind in KINDS:
        for object_id, definition in definitions[kind].items():
            path = f"{kind}.{object_id}"
            _positive_integer(definition.get("评分"), f"{path}.评分")
            for field in META_FIELDS:
                values = _string_list(definition.get(field), f"{path}.{field}")
                if len(values) != len(set(values)):
                    raise ValueError(f"{path}.{field}不能重复")
            composition = _sequence(definition, "组成")
            active_nodes = [value for value in composition if value.get("能力") == "主动技能"]
            passive_nodes = [value for value in composition if value.get("能力") == "被动技能"]
            if kind == "功法":
                role = str(definition.get("职责") or "")
                if role not in {"主动", "被动"}:
                    raise ValueError(f"{path}.职责必须为主动或被动")
                if role == "主动" and (len(active_nodes), len(passive_nodes)) != (1, 0):
                    raise ValueError(f"{path}的主动职责必须且只能装配一个主动技能")
                if role == "被动" and (len(active_nodes), len(passive_nodes)) != (0, 1):
                    raise ValueError(f"{path}的被动职责必须且只能装配一个被动技能")
            elif kind == "附魔":
                if active_nodes or len(passive_nodes) != 1:
                    raise ValueError(f"{path}必须且只能装配一个被动技能")
            elif active_nodes or passive_nodes:
                raise ValueError(f"{path}只能提供属性或已有机制增幅，不能装配技能")

            for node in active_nodes:
                order = _positive_integer(node.get("释放顺序"), f"{path}.释放顺序")
                _claim_order(release_orders, order, path, "释放顺序")
            for node in passive_nodes:
                order = _positive_integer(node.get("结算顺序"), f"{path}.结算顺序")
                _claim_order(settlement_orders, order, path, "结算顺序")


def _validate_direction_catalog(
    *,
    combination: Mapping[str, Any],
    balance: Mapping[str, Any],
    directions: Mapping[str, Mapping[str, Any]],
    group_directions: Mapping[str, Mapping[str, str]],
    groups: Mapping[str, Mapping[str, Sequence[str]]],
    definitions: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> None:
    expected = int(combination["方向数量"])
    if len(directions) != expected:
        raise ValueError(f"战斗方向必须正好有{expected}个，当前为{len(directions)}个")
    fingerprints: dict[tuple[str, ...], str] = {}
    minimums = _mapping(combination, "方向候选下限")
    inverse_groups = {
        kind: _invert_unique(group_directions[kind], kind)
        for kind in KINDS
    }
    global_dimensions = tuple(_mapping(balance, "评分维度"))
    for direction_id, direction in directions.items():
        path = f"战斗方向.{direction_id}"
        if str(direction.get("名称") or "") != direction_id:
            raise ValueError(f"{path}.名称必须与目录键一致")
        for field in ("定位", "核心状态", "进攻方式", "防御方式"):
            if not str(direction.get(field) or "").strip():
                raise ValueError(f"{path}.{field}不能为空")
        loop = tuple(_string_list(direction.get("核心循环"), f"{path}.核心循环"))
        if len(loop) < 4:
            raise ValueError(f"{path}.核心循环至少需要4步")
        if loop in fingerprints:
            raise ValueError(f"{path}.核心循环与{fingerprints[loop]}重复")
        fingerprints[loop] = direction_id
        for field in ("优势场景", "弱势场景"):
            if len(_string_list(direction.get(field), f"{path}.{field}")) < 2:
                raise ValueError(f"{path}.{field}至少需要2项")
        model = _mapping(direction, "评分模型")
        for field in ("主指标", "辅助指标", "惩罚项"):
            if len(_string_list(model.get(field), f"{path}.评分模型.{field}")) < 2:
                raise ValueError(f"{path}.评分模型.{field}至少需要2项")
        weights = _mapping(model, "维度权重")
        if tuple(weights) != global_dimensions:
            raise ValueError(f"{path}.评分模型.维度权重必须覆盖八个评分维度")
        if sum(_positive_integer(value, f"{path}.评分模型.维度权重.{key}") for key, value in weights.items()) != 100:
            raise ValueError(f"{path}.评分模型.维度权重合计必须为100")

        direction_candidates: dict[str, tuple[str, ...]] = {}
        for kind in KINDS:
            group_id = inverse_groups[kind].get(direction_id)
            if group_id is None:
                raise ValueError(f"{path}缺少{kind}池")
            object_ids = tuple(str(value) for value in groups[kind][group_id])
            if len(object_ids) < int(minimums[kind]):
                raise ValueError(f"{path}的{kind}池至少需要{int(minimums[kind])}项")
            direction_candidates[kind] = object_ids

        for slot in _sequence(combination, "校验槽位"):
            count = int(slot)
            role_rule = _mapping(_mapping(combination, "功法职责"), str(count))
            if not has_compatible_loadout(
                candidates=direction_candidates,
                definitions=definitions,
                count=count,
                active_minimum=int(role_rule["主动最少"]),
                passive_minimum=int(role_rule["被动最少"]),
            ):
                raise ValueError(f"{path}无法组成合法的{count}槽构筑")


def _invert_unique(values: Mapping[str, str], kind: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for group_id, direction_id in values.items():
        if direction_id in result:
            raise ValueError(f"战斗方向{direction_id}重复绑定两个{kind}池")
        result[str(direction_id)] = str(group_id)
    return result


def _claim_order(values: dict[int, str], order: int, path: str, field: str) -> None:
    previous = values.get(order)
    if previous is not None:
        raise ValueError(f"{path}.{field}与{previous}重复：{order}")
    values[order] = path


def _mapping(value: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    result = value.get(field)
    if not isinstance(result, Mapping):
        raise ValueError(f"{field}必须是对象")
    return result


def _sequence(value: Mapping[str, Any], field: str) -> Sequence[Any]:
    result = value.get(field)
    if not isinstance(result, list):
        raise ValueError(f"{field}必须是数组")
    return result


def _string_list(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not str(item).strip() for item in value):
        raise ValueError(f"{path}必须是非空字符串数组")
    return tuple(str(item) for item in value)


def _positive_integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{path}必须是正整数")
    return value


def _percentage(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
        raise ValueError(f"{path}必须是0到100之间的数字")
    return float(value)


__all__ = ["validate_battle_design"]
