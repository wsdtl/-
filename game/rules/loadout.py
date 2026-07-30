"""功法、附魔和宝石的统一组合约束。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from itertools import combinations
import random
from typing import Any


KINDS = ("功法", "附魔", "宝石")


def compatibility_issues(
    selected: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
    *,
    active_minimum: int = 0,
    passive_minimum: int = 0,
) -> tuple[str, ...]:
    """返回一套装配的全部组合问题；空元组表示可以正常装配。"""

    entries = [
        (kind, object_id, definition)
        for kind in KINDS
        for object_id, definition in selected.get(kind, ())
    ]
    issues: list[str] = []
    provided_by_entry = [set(_strings(value, "提供标签")) for _, _, value in entries]
    for index, (kind, object_id, definition) in enumerate(entries):
        other_provided = set().union(
            *(tags for other_index, tags in enumerate(provided_by_entry) if other_index != index)
        )
        missing = set(_strings(definition, "需要标签")) - other_provided
        if missing:
            issues.append(f"{kind}{object_id}缺少标签：{'、'.join(sorted(missing))}")
        forbidden = set(_strings(definition, "禁止标签")) & other_provided
        if forbidden:
            issues.append(f"{kind}{object_id}遇到禁止标签：{'、'.join(sorted(forbidden))}")

    mutex_entries: dict[str, list[str]] = {}
    for kind, object_id, definition in entries:
        for group in _strings(definition, "互斥组"):
            mutex_entries.setdefault(group, []).append(f"{kind}{object_id}")
    for group, members in mutex_entries.items():
        if len(members) > 1:
            issues.append(f"互斥组{group}同时出现：{'、'.join(members)}")

    roles = Counter(
        str(definition.get("职责") or "")
        for _, definition in selected.get("功法", ())
    )
    if roles["主动"] < int(active_minimum):
        issues.append(f"主动功法不足{int(active_minimum)}门")
    if roles["被动"] < int(passive_minimum):
        issues.append(f"被动功法不足{int(passive_minimum)}门")
    return tuple(issues)


def choose_compatible_loadout(
    *,
    candidates: Mapping[str, Sequence[str]],
    definitions: Mapping[str, Mapping[str, Mapping[str, Any]]],
    counts: Mapping[str, int],
    samplers: Mapping[str, Callable[[Sequence[str], int, random.Random], Sequence[str]]],
    rng: random.Random,
    attempts: int,
    active_minimum: int,
    passive_minimum: int,
) -> dict[str, tuple[str, ...]]:
    """按各目录权重随机，直到得到一套合法构筑。"""

    last_issues: tuple[str, ...] = ()
    for _ in range(max(1, int(attempts))):
        chosen = {
            kind: tuple(samplers[kind](tuple(candidates[kind]), int(counts[kind]), rng))
            for kind in KINDS
        }
        selected = {
            kind: tuple((object_id, definitions[kind][object_id]) for object_id in chosen[kind])
            for kind in KINDS
        }
        last_issues = compatibility_issues(
            selected,
            active_minimum=active_minimum,
            passive_minimum=passive_minimum,
        )
        if not last_issues:
            return chosen
    detail = "；".join(last_issues) or "没有候选内容"
    raise ValueError(f"无法生成合法战斗构筑：{detail}")


def has_compatible_loadout(
    *,
    candidates: Mapping[str, Sequence[str]],
    definitions: Mapping[str, Mapping[str, Mapping[str, Any]]],
    count: int,
    active_minimum: int,
    passive_minimum: int,
) -> bool:
    """启动校验只寻找一套可行解，不执行昂贵的全池战斗模拟。"""

    subsets: dict[str, Iterable[tuple[str, ...]]] = {
        kind: combinations(tuple(candidates[kind]), int(count))
        for kind in KINDS
    }
    technique_subsets = tuple(
        subset
        for subset in subsets["功法"]
        if _role_count(subset, definitions["功法"], "主动") >= active_minimum
        and _role_count(subset, definitions["功法"], "被动") >= passive_minimum
    )
    enchantment_subsets = tuple(subsets["附魔"])
    gem_subsets = tuple(subsets["宝石"])
    for techniques in technique_subsets:
        technique_values = tuple((key, definitions["功法"][key]) for key in techniques)
        for enchantments in enchantment_subsets:
            enchantment_values = tuple((key, definitions["附魔"][key]) for key in enchantments)
            for gems in gem_subsets:
                selected = {
                    "功法": technique_values,
                    "附魔": enchantment_values,
                    "宝石": tuple((key, definitions["宝石"][key]) for key in gems),
                }
                if not compatibility_issues(
                    selected,
                    active_minimum=active_minimum,
                    passive_minimum=passive_minimum,
                ):
                    return True
    return False


def _role_count(
    object_ids: Sequence[str],
    definitions: Mapping[str, Mapping[str, Any]],
    role: str,
) -> int:
    return sum(str(definitions[object_id].get("职责") or "") == role for object_id in object_ids)


def _strings(value: Mapping[str, Any], field: str) -> tuple[str, ...]:
    raw = value.get(field) or ()
    return tuple(str(item) for item in raw)


__all__ = [
    "KINDS",
    "choose_compatible_loadout",
    "compatibility_issues",
    "has_compatible_loadout",
]
