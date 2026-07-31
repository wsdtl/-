"""执行 JSON 声明的角色等级阶梯与属性成长。"""

from __future__ import annotations

from collections.abc import Mapping
import copy
from typing import Any


def resolve_level_tier(rule: Mapping[str, Any], level: int) -> Mapping[str, Any]:
    """按最终等级选择唯一阶梯，不猜测缺口或重叠。"""

    final_level = max(1, int(level))
    matches = []
    for raw in rule.get("阶梯") or ():
        tier = dict(raw)
        bounds = tier.get("等级范围") or ()
        if len(bounds) != 2:
            raise ValueError("角色阶梯.等级范围必须包含起止等级")
        low, high = (int(bounds[0]), int(bounds[1]))
        if low <= final_level <= high:
            matches.append(tier)
    if len(matches) != 1:
        raise ValueError(f"等级 {final_level} 必须且只能命中一个角色阶梯")
    return matches[0]


def resolve_tiered_character(
    *,
    rule: Mapping[str, Any],
    level: int,
    base_attributes: Mapping[str, float],
    standard_growth: Mapping[str, float],
) -> dict[str, Any]:
    """组合共享成长与阶梯修正，返回可直接交给战斗快照的数据。"""

    final_level = max(1, int(level))
    tier = resolve_level_tier(rule, final_level)
    growth = dict(tier.get("成长修正") or {})
    tier_per_level = dict(growth.get("每级") or {})
    tier_fixed = dict(growth.get("固定") or {})
    known = set(base_attributes)
    unknown = (set(standard_growth) | set(tier_per_level) | set(tier_fixed)) - known
    if unknown:
        raise ValueError("角色成长引用未知属性：" + "、".join(sorted(str(value) for value in unknown)))

    steps = final_level - 1
    attributes = {
        str(name): float(base)
        + float(standard_growth.get(name, 0)) * steps
        + float(tier_per_level.get(name, 0)) * steps
        + float(tier_fixed.get(name, 0))
        for name, base in base_attributes.items()
    }
    return {
        "阶梯": str(tier.get("名称") or ""),
        "等级": final_level,
        "属性": attributes,
        "构筑": {
            "功法位": int(tier["功法位"]),
            "附魔位": int(tier["附魔位"]),
            "宝石位": int(tier["宝石位"]),
        },
        "战斗规格": copy.deepcopy(dict(tier.get("战斗规格") or {})),
    }


__all__ = ["resolve_level_tier", "resolve_tiered_character"]
