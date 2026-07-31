"""功法、附魔和宝石共用的机制相冲约束。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import random
from typing import Any


KINDS = ("功法", "附魔", "宝石")
REFERENCE_ABILITIES = frozenset({"引用战斗机制", "引用被动机制"})


def mechanism_references(
    value: Any,
    mechanisms: Mapping[str, Mapping[str, Any]],
) -> frozenset[str]:
    """递归展开一份实体实际会使用的全部机制编号。"""

    found: set[str] = set()
    expanded: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            if str(node.get("能力") or "") in REFERENCE_ABILITIES:
                identity = str(node.get("机制") or "")
                if identity:
                    found.add(identity)
                    if identity not in expanded:
                        expanded.add(identity)
                        definition = mechanisms.get(identity)
                        if definition is not None:
                            visit(definition.get("节点", definition))
            for child in node.values():
                visit(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                visit(child)

    visit(value)
    return frozenset(found)


def compatibility_issues(
    selected: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
    *,
    mechanisms: Mapping[str, Mapping[str, Any]],
    conflicts: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """返回真实机制组合触犯的相冲法则；空元组表示可以装配。"""

    owners: dict[str, list[str]] = {}
    for kind in KINDS:
        for object_id, definition in selected.get(kind, ()):
            for mechanism_id in mechanism_references(definition, mechanisms):
                owners.setdefault(mechanism_id, []).append(f"{kind}{object_id}")

    issues: list[str] = []
    for rule in conflicts:
        name = str(rule.get("名称") or "未命名相冲")
        members = tuple(dict.fromkeys(str(value) for value in rule.get("机制") or ()))
        present = [identity for identity in members if identity in owners]
        if len(present) < 2:
            continue
        sources = "、".join(
            f"{identity}({','.join(owners[identity])})"
            for identity in present
        )
        issues.append(f"触犯{name}：{sources}")
    return tuple(issues)


def choose_compatible_loadout(
    *,
    candidates: Mapping[str, Sequence[str]],
    definitions: Mapping[str, Mapping[str, Mapping[str, Any]]],
    mechanisms: Mapping[str, Mapping[str, Any]],
    conflicts: Sequence[Mapping[str, Any]],
    counts: Mapping[str, int],
    samplers: Mapping[str, Callable[[Sequence[str], int, random.Random], Sequence[str]]],
    rng: random.Random,
    attempts: int,
) -> dict[str, tuple[str, ...]]:
    """从三个独立全池抽取，拒绝真实机制相冲的组合。"""

    last_issues: tuple[str, ...] = ()
    for _ in range(max(1, int(attempts))):
        chosen = {
            kind: tuple(samplers[kind](tuple(candidates[kind]), int(counts[kind]), rng))
            for kind in KINDS
        }
        selected = {
            kind: tuple((identity, definitions[kind][identity]) for identity in chosen[kind])
            for kind in KINDS
        }
        last_issues = compatibility_issues(
            selected,
            mechanisms=mechanisms,
            conflicts=conflicts,
        )
        if not last_issues:
            return chosen
    detail = "；".join(last_issues) or "候选池为空或数量不足"
    raise ValueError(f"无法生成合法战斗构筑：{detail}")


__all__ = [
    "KINDS",
    "choose_compatible_loadout",
    "compatibility_issues",
    "mechanism_references",
]
