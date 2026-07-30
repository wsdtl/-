"""功法、附魔和宝石共用的构筑生成与战斗展开。"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Mapping, Sequence

from game.content import GameContent
from game.rules.loadout import KINDS, choose_compatible_loadout


@dataclass(frozen=True)
class RolledLoadout:
    direction_id: str | None
    techniques: tuple[dict[str, Any], ...]
    enchantments: tuple[dict[str, Any], ...]
    gems: tuple[dict[str, Any], ...]


def direction_candidates(
    content: GameContent,
    direction_id: str,
) -> dict[str, tuple[str, ...]]:
    direction = str(direction_id)
    group_maps = {
        "功法": (content.technique_groups, content.technique_group_directions),
        "附魔": (content.enchantment_groups, content.enchantment_group_directions),
        "宝石": (content.gem_groups, content.gem_group_directions),
    }
    result: dict[str, tuple[str, ...]] = {}
    for kind, (groups, directions) in group_maps.items():
        group_id = next(
            (key for key, value in directions.items() if value == direction),
            None,
        )
        if group_id is None:
            raise ValueError(f"战斗方向{direction}缺少{kind}池")
        result[kind] = tuple(groups[group_id])
    return result


def global_candidates(
    content: GameContent,
    rng: random.Random,
    *,
    theme_limit: int = 3,
) -> dict[str, tuple[str, ...]]:
    """从全池随机若干兼容战术，使每项内容仍有机会进入首领构筑。"""

    definitions = _definitions(content)
    technique_ids = tuple(definitions["功法"])
    theme_tags = tuple(
        dict.fromkeys(
            tag
            for object_id in technique_ids
            for tag in _tags(definitions["功法"][object_id], "提供标签")
            if tag.startswith("战术:")
        )
    )
    if not theme_tags:
        raise ValueError("全池没有可用的战术标签")
    requested = rng.randint(1, min(max(1, int(theme_limit)), len(theme_tags)))
    selected: list[str] = []
    shuffled = list(theme_tags)
    rng.shuffle(shuffled)
    for theme in shuffled:
        if any(_themes_conflict(theme, previous, definitions) for previous in selected):
            continue
        selected.append(theme)
        if len(selected) == requested:
            break
    selected_tags = set(selected)
    if not selected_tags:
        selected_tags.add(shuffled[0])

    result: dict[str, tuple[str, ...]] = {}
    for kind in KINDS:
        candidates = tuple(
            object_id
            for object_id, definition in definitions[kind].items()
            if selected_tags.intersection(_tags(definition, "提供标签"))
            and not selected_tags.intersection(_tags(definition, "禁止标签"))
        )
        if not candidates:
            raise ValueError(f"全池战术筛选后没有{kind}候选")
        result[kind] = candidates
    return result


def roll_loadout(
    content: GameContent,
    rng: random.Random,
    *,
    candidates: Mapping[str, Sequence[str]],
    counts: Mapping[str, int],
    direction_id: str | None = None,
    grade_id: str | None = None,
) -> RolledLoadout:
    technique_count = int(counts["功法"])
    role_rule = content.combination_rules["功法职责"][str(technique_count)]
    chosen = choose_compatible_loadout(
        candidates=candidates,
        definitions=_definitions(content),
        counts=counts,
        samplers={
            "功法": lambda values, count, source: _sample(
                values,
                count,
                content.choose_technique,
                source,
            ),
            "附魔": lambda values, count, source: _sample(
                values,
                count,
                content.choose_enchantment,
                source,
            ),
            "宝石": lambda values, count, source: _sample(
                values,
                count,
                content.choose_gem,
                source,
            ),
        },
        rng=rng,
        attempts=int(content.combination_rules["生成尝试上限"]),
        active_minimum=int(role_rule["主动最少"]),
        passive_minimum=int(role_rule["被动最少"]),
    )
    return RolledLoadout(
        direction_id=str(direction_id) if direction_id is not None else None,
        techniques=tuple(
            _roll_technique(content, technique_id, rng, grade_id=grade_id)
            for technique_id in chosen["功法"]
        ),
        enchantments=tuple(
            {
                "名称": augment_id,
                "品级": str(grade_id or content.choose_grade(rng)),
            }
            for augment_id in chosen["附魔"]
        ),
        gems=tuple(
            {
                "名称": augment_id,
                "品级": str(grade_id or content.choose_grade(rng)),
            }
            for augment_id in chosen["宝石"]
        ),
    )


def configure_battle_instances(
    content: GameContent,
    *,
    techniques: Sequence[Mapping[str, Any]],
    enchantments: Sequence[Mapping[str, Any]],
    gems: Sequence[Mapping[str, Any]],
    instance_prefix: str,
) -> tuple[dict[str, Any], ...]:
    result = content.configured_battle_techniques(
        [dict(value) for value in techniques],
        instance_prefix=instance_prefix,
    )
    for kind, values in (("附魔", enchantments), ("宝石", gems)):
        for index, value in enumerate(values, start=1):
            result.append(
                content.configured_weapon_augment(
                    kind,
                    str(value["名称"]),
                    str(value["品级"]),
                    instance_id=f"{instance_prefix}:{kind}:{index}",
                )
            )
    return tuple(result)


def _definitions(
    content: GameContent,
) -> dict[str, Mapping[str, Mapping[str, Any]]]:
    return {
        "功法": content.technique_definitions,
        "附魔": content.enchantment_definitions,
        "宝石": content.gem_definitions,
    }


def _sample(
    candidates: Sequence[str],
    count: int,
    chooser,
    rng: random.Random,
) -> tuple[str, ...]:
    remaining = list(dict.fromkeys(str(value) for value in candidates))
    required = max(0, int(count))
    if len(remaining) < required:
        raise ValueError(f"候选池只有{len(remaining)}项，无法抽取{required}项")
    result: list[str] = []
    for _ in range(required):
        selected = str(chooser(tuple(remaining), rng))
        if selected not in remaining:
            raise ValueError(f"加权选择器返回了候选池之外的内容：{selected}")
        result.append(selected)
        remaining.remove(selected)
    return tuple(result)


def _roll_technique(
    content: GameContent,
    technique_id: str,
    rng: random.Random,
    *,
    grade_id: str | None = None,
) -> dict[str, Any]:
    definition = content.technique_definitions[str(technique_id)]
    grade = str(grade_id or content.choose_grade(rng))
    affix_count = int(content.grade_definitions[grade]["词条数量"])
    affix_ids = _sample(
        tuple(str(value) for value in definition["随机词条"]),
        affix_count,
        content.choose_affix,
        rng,
    )
    return {
        "功法": str(technique_id),
        "品级": grade,
        "词条": [
            _roll_affix(affix_id, content.affix_definitions[affix_id], rng)
            for affix_id in affix_ids
        ],
    }


def _roll_affix(
    affix_id: str,
    definition: Mapping[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    minimum = float(definition["最小值"])
    maximum = float(definition["最大值"])
    value: int | float
    if minimum.is_integer() and maximum.is_integer():
        value = rng.randint(int(minimum), int(maximum))
    else:
        value = round(rng.uniform(minimum, maximum), 4)
    return {
        "词条": str(affix_id),
        "属性": str(definition["属性"]),
        "数值": value,
        "最小值": minimum,
        "最大值": maximum,
    }


def _themes_conflict(
    left: str,
    right: str,
    definitions: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> bool:
    for values in definitions.values():
        for definition in values.values():
            provided = set(_tags(definition, "提供标签"))
            if left in provided and right in _tags(definition, "禁止标签"):
                return True
            if right in provided and left in _tags(definition, "禁止标签"):
                return True
    return False


def _tags(definition: Mapping[str, Any], field: str) -> tuple[str, ...]:
    return tuple(str(value) for value in definition.get(field) or ())


__all__ = [
    "RolledLoadout",
    "configure_battle_instances",
    "direction_candidates",
    "global_candidates",
    "roll_loadout",
]
