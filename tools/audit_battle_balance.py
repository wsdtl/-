"""离线审查264个战斗方向的构筑质量与真实战斗表现。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import random
from statistics import fmean, pstdev
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import GameContent
from game.core import JsonDataReader
from game.features.loadout import (
    RolledLoadout,
    configure_battle_instances,
    direction_candidates,
    roll_loadout,
)
from game.rules import BattleEngine, CombatantSnapshot


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
DEFAULT_BALANCE_PATH = ROOT / "tools" / "战斗校验" / "平衡.json"


def audit(
    *,
    data_dir: Path,
    balance_path: Path = DEFAULT_BALANCE_PATH,
    output_path: Path,
    builds_per_direction: int | None = None,
    seeds_per_match: int | None = None,
) -> dict[str, Any]:
    content = GameContent.load(JsonDataReader(data_dir))
    balance = JsonDataReader(balance_path.parent).read(balance_path.name)
    sample_rule = balance["战斗抽样"]
    build_count = int(builds_per_direction or sample_rule["每方向构筑数"])
    seed_count = int(seeds_per_match or sample_rule["每组对战种子数"])
    action_limit = int(sample_rule["行动上限"])
    directions = tuple(sorted(content.direction_definitions))
    grades = tuple(str(value) for value in balance["测试品级"])
    slots = tuple(int(value) for value in balance["测试槽位"])

    build_scores: dict[str, list[float]] = defaultdict(list)
    for direction_id in directions:
        candidates = direction_candidates(content, direction_id)
        for slot in slots:
            counts = {kind: slot for kind in ("功法", "附魔", "宝石")}
            for grade_id in grades:
                for sample in range(build_count):
                    seed = _seed("构筑", direction_id, slot, grade_id, sample)
                    loadout = roll_loadout(
                        content,
                        random.Random(seed),
                        candidates=candidates,
                        counts=counts,
                        direction_id=direction_id,
                        grade_id=grade_id,
                    )
                    build_scores[direction_id].append(
                        _normalized_content_score(content, balance, loadout)
                    )

    engine = BattleEngine(content.combat)
    item_definitions = content.combat_item_definitions()
    scenario_directions = _scenario_directions(content, balance)
    battle_values: dict[str, dict[str, list[float]]] = {
        direction_id: {dimension: [] for dimension in DIMENSIONS}
        for direction_id in directions
    }
    wins: dict[str, float] = defaultdict(float)
    matches: dict[str, int] = defaultdict(int)
    performance: dict[str, list[float]] = defaultdict(list)
    battle_grade = grades[len(grades) // 2]
    battle_slot = max(slots)
    counts = {kind: battle_slot for kind in ("功法", "附魔", "宝石")}

    for direction_id in directions:
        left_candidates = direction_candidates(content, direction_id)
        for scenario_dimension, opponent_direction in scenario_directions.items():
            right_candidates = direction_candidates(content, opponent_direction)
            for sample in range(seed_count):
                seed = _seed(
                    "实战",
                    direction_id,
                    scenario_dimension,
                    opponent_direction,
                    sample,
                )
                left = roll_loadout(
                    content,
                    random.Random(seed ^ 0x243F6A8885A308D3),
                    candidates=left_candidates,
                    counts=counts,
                    direction_id=direction_id,
                    grade_id=battle_grade,
                )
                right = roll_loadout(
                    content,
                    random.Random(seed ^ 0x13198A2E03707344),
                    candidates=right_candidates,
                    counts=counts,
                    direction_id=opponent_direction,
                    grade_id=battle_grade,
                )
                outcome = engine.simulate(
                    left=_snapshot(content, left, "left"),
                    right=_snapshot(content, right, "right"),
                    item_definitions=item_definitions,
                    seed=seed,
                    action_limit=action_limit,
                )
                raw = _battle_metrics(outcome)
                for dimension, value in raw.items():
                    if dimension != "稳定性":
                        battle_values[direction_id][dimension].append(value)
                performance[direction_id].append(raw["输出"] + raw["生存"])
                matches[direction_id] += 1
                if outcome.winner_side == "left":
                    wins[direction_id] += 1.0
                elif outcome.winner_side is None:
                    wins[direction_id] += 0.5

    raw_averages: dict[str, dict[str, float]] = {}
    for direction_id in directions:
        raw_averages[direction_id] = {
            dimension: (
                _stability(performance[direction_id])
                if dimension == "稳定性"
                else fmean(battle_values[direction_id][dimension])
            )
            for dimension in DIMENSIONS
        }
    dimension_scores = _normalize_dimensions(raw_averages)

    direction_results: dict[str, dict[str, Any]] = {}
    composites: list[float] = []
    for direction_id in directions:
        definition = content.direction_definitions[direction_id]
        weights = balance["方向评分模型"][direction_id]["维度权重"]
        evidence = matches[direction_id]
        confidence = evidence / (evidence + 24.0)
        adjusted_dimensions = {
            dimension: 50.0
            + (dimension_scores[direction_id][dimension] - 50.0) * confidence
            for dimension in DIMENSIONS
        }
        weighted_battle = sum(
            adjusted_dimensions[dimension] * float(weights[dimension])
            for dimension in DIMENSIONS
        ) / 100.0
        scores = build_scores[direction_id]
        p10 = _percentile(scores, 10)
        p50 = _percentile(scores, 50)
        p90 = _percentile(scores, 90)
        observed_win_rate = wins[direction_id] * 100.0 / max(1, evidence)
        adjusted_win_rate = (
            wins[direction_id] + 12.0
        ) * 100.0 / (evidence + 24.0)
        composite = p50 * 0.35 + weighted_battle * 0.55 + adjusted_win_rate * 0.10
        composites.append(composite)
        direction_results[direction_id] = {
            "定位": definition["定位"],
            "构筑评分": {
                "P10": round(p10, 3),
                "P50": round(p50, 3),
                "P90": round(p90, 3),
            },
            "八维评分": {
                key: round(adjusted_dimensions[key], 3)
                for key in DIMENSIONS
            },
            "观测胜率百分比": round(observed_win_rate, 3),
            "校正胜率百分比": round(adjusted_win_rate, 3),
            "综合评分": round(composite, 3),
            "实战场次": matches[direction_id],
        }

    weakest = min(direction_results, key=lambda key: direction_results[key]["综合评分"])
    strongest = max(direction_results, key=lambda key: direction_results[key]["综合评分"])
    low = direction_results[weakest]["综合评分"]
    high = direction_results[strongest]["综合评分"]
    gap = 100.0 if low <= 0 else (high / low - 1.0) * 100.0
    thresholds = balance["方向差距"]
    target = float(thresholds["目标百分比"])
    rejected = float(thresholds["拒绝百分比"])
    if gap > rejected:
        verdict = "拒绝"
    elif gap > target:
        verdict = "预警"
    else:
        verdict = "通过"

    report = {
        "版本": "晓楠修仙.战斗平衡审查.v1",
        "结论": verdict,
        "摘要": {
            "方向数量": len(directions),
            "构筑抽样数量": len(directions) * len(slots) * len(grades) * build_count,
            "真实战斗数量": sum(matches.values()),
            "标准场景": scenario_directions,
            "最弱方向": weakest,
            "最强方向": strongest,
            "综合差距百分比": round(gap, 3),
            "目标百分比": target,
            "拒绝百分比": rejected,
        },
        "方向": direction_results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _normalized_content_score(
    content: GameContent,
    balance: Mapping[str, Any],
    loadout: RolledLoadout,
) -> float:
    baseline = balance["内容评分基准"]
    actual = 0.0
    expected = 0.0
    for technique in loadout.techniques:
        definition = content.technique_definitions[str(technique["功法"])]
        multiplier = float(content.grade_definitions[str(technique["品级"])]["能力倍率"])
        role = str(definition["职责"])
        actual += float(definition["评分"]) * multiplier
        expected += float(baseline[f"{role}功法"]) * multiplier
        actual += sum(_affix_value(value) for value in technique["词条"])
    for kind, values, definitions, baseline_key in (
        ("附魔", loadout.enchantments, content.enchantment_definitions, "附魔"),
        ("宝石", loadout.gems, content.gem_definitions, "宝石"),
    ):
        for value in values:
            multiplier = float(content.grade_definitions[str(value["品级"])]["能力倍率"])
            actual += float(definitions[str(value["名称"])]["评分"]) * multiplier
            expected += float(baseline[baseline_key]) * multiplier
    return actual * 100.0 / max(1.0, expected)


def _affix_value(value: Mapping[str, Any]) -> float:
    minimum = float(value["最小值"])
    maximum = float(value["最大值"])
    ratio = 0.5 if maximum <= minimum else (float(value["数值"]) - minimum) / (maximum - minimum)
    return 2.0 + max(0.0, min(1.0, ratio)) * 3.0


def _scenario_directions(
    content: GameContent,
    balance: Mapping[str, Any],
) -> dict[str, str]:
    result: dict[str, str] = {}
    used: set[str] = set()
    for dimension in DIMENSIONS:
        ordered = sorted(
            content.direction_definitions,
            key=lambda direction_id: (
                -int(
                    balance["方向评分模型"][direction_id]["维度权重"][dimension]
                ),
                direction_id,
            ),
        )
        direction_id = next(
            (value for value in ordered if value not in used),
            ordered[0],
        )
        used.add(direction_id)
        result[dimension] = direction_id
    return result


def _snapshot(
    content: GameContent,
    loadout: RolledLoadout,
    side: str,
) -> CombatantSnapshot:
    attributes = {
        str(key): float(value)
        for key, value in content.player["人物"]["属性"].items()
    }
    instances = configure_battle_instances(
        content,
        techniques=loadout.techniques,
        enchantments=loadout.enchantments,
        gems=loadout.gems,
        instance_prefix=f"audit:{side}",
    )
    return CombatantSnapshot(
        id=side,
        name=side,
        attributes=attributes,
        level=1,
        kind="修士",
        weapon_attack=float(content.player["本命武器"]["基础攻击"]),
        techniques=instances,
        health=float(attributes["血气上限"]),
        spirit=float(attributes["精神上限"]),
    )


def _battle_metrics(outcome) -> dict[str, float]:
    actions = max(1, int(outcome.actions))
    damage = sum(
        max(0.0, float(event.amount))
        for event in outcome.events
        if event.kind == "damage" and event.source_id == "left"
    )
    early_damage = sum(
        max(0.0, float(event.amount))
        for event in outcome.events
        if event.kind == "damage"
        and event.source_id == "left"
        and event.turn <= min(3, actions)
    )
    sustain = sum(
        max(0.0, float(event.amount))
        for event in outcome.events
        if event.kind in {"recover", "heal"} and event.target_id == "left"
    )
    control = sum(
        1.0
        for event in outcome.events
        if event.source_id == "left"
        and event.target_id == "right"
        and event.kind in {"status", "action_progress"}
    )
    cleansed = sum(
        1.0
        for event in outcome.events
        if event.kind == "status_end"
        and event.target_id == "left"
        and event.values.get("分类") in {"负面", "控制"}
    )
    support = sum(
        1.0
        for event in outcome.events
        if event.source_id == "left"
        and event.target_id == "left"
        and event.kind in {"status", "recover", "heal", "action_progress"}
    )
    spirit_cost = sum(
        max(0.0, float(event.values.get("资源消耗") or 0.0))
        for event in outcome.events
        if event.kind == "skill" and event.source_id == "left"
    )
    health_max = max(1.0, float(outcome.left.attributes.get("血气上限", 100.0)))
    survival = max(0.0, outcome.left.health + outcome.left.shield) * 100.0 / health_max
    return {
        "输出": damage / actions,
        "生存": survival + cleansed * 3.0,
        "控制": (control + cleansed * 0.5) * 100.0 / actions,
        "续航": sustain / actions + cleansed,
        "启动速度": early_damage / max(1, min(3, actions)),
        "资源效率": damage / max(1.0, spirit_cost),
        "稳定性": 0.0,
        "团队价值": (support + cleansed) * 100.0 / actions,
    }


def _stability(values: Sequence[float]) -> float:
    average = fmean(values) if values else 0.0
    if average <= 0:
        return 0.0
    return 100.0 / (1.0 + pstdev(values) / average)


def _normalize_dimensions(
    values: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, float]]:
    result = {direction_id: {} for direction_id in values}
    for dimension in DIMENSIONS:
        population = [value[dimension] for value in values.values()]
        low = _percentile(population, 10)
        high = _percentile(population, 90)
        for direction_id, metrics in values.items():
            if math.isclose(high, low):
                score = 50.0
            else:
                score = (metrics[dimension] - low) * 100.0 / (high - low)
            result[direction_id][dimension] = max(0.0, min(100.0, score))
    return result


def _percentile(values: Sequence[float], percentage: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * float(percentage) / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    ratio = position - lower
    return ordered[lower] * (1.0 - ratio) + ordered[upper] * ratio


def _seed(*values: Any) -> int:
    digest = sha256("|".join(str(value) for value in values).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--balance", type=Path, default=DEFAULT_BALANCE_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "log" / "战斗平衡审查.json")
    parser.add_argument("--builds", type=int)
    parser.add_argument("--seeds", type=int)
    args = parser.parse_args()
    report = audit(
        data_dir=args.data,
        balance_path=args.balance,
        output_path=args.output,
        builds_per_direction=args.builds,
        seeds_per_match=args.seeds,
    )
    summary = report["摘要"]
    print(
        f"balance={report['结论']} directions={summary['方向数量']} "
        f"builds={summary['构筑抽样数量']} battles={summary['真实战斗数量']} "
        f"gap={summary['综合差距百分比']}% "
        f"weakest={summary['最弱方向']} strongest={summary['最强方向']}"
    )
    return 1 if report["结论"] == "拒绝" else 0


if __name__ == "__main__":
    raise SystemExit(main())
