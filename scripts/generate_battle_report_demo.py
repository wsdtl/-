"""使用真实战斗核心生成本地战报演示，不读写游戏数据库。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import GameContent
from game.core import JsonDataReader
from game.features.diren import EnemyFeature
from game.rules import BattleEngine, CombatantSnapshot
from game.rules.battle import (
    BattleReportParticipant,
    build_battle_report,
    build_battle_report_presentation,
)


def _affix(content: GameContent, name: str) -> dict[str, Any]:
    definition = content.affix_definitions[name]
    minimum = float(definition["最小值"])
    maximum = float(definition["最大值"])
    value = round(minimum + (maximum - minimum) * 0.35, 2)
    return {
        "词条": name,
        "属性": definition["属性"],
        "数值": value,
        "最小值": minimum,
        "最大值": maximum,
    }


def _technique(
    content: GameContent,
    name: str,
    born_order: int,
    affix_name: str,
) -> dict[str, Any]:
    definition = content.technique_definitions[name]
    return {
        "实例": f"demo-technique-{born_order}",
        "功法": name,
        "品级": "凡品",
        "出生序号": born_order,
        "威力倍率": float(content.rarity_definitions["凡品"]["威力倍率"]),
        "词条": [_affix(content, affix_name)],
        "能力": [dict(value) for value in definition.get("组成") or ()],
    }


def generate_report() -> tuple[dict[str, Any], dict[str, Any]]:
    content = GameContent.load(JsonDataReader(ROOT / "data"))
    engine = BattleEngine(content.combat)
    techniques = [
        _technique(content, "离火归元诀", 1, "神完气足"),
        _technique(content, "北斗御神篇", 2, "身轻如燕"),
        _technique(content, "踏罡行气经", 3, "攻伐精进"),
    ]

    weapon_attack = 10.0
    player_attributes = dict(content.player["人物"]["属性"])

    enemy_name = "石门守修"
    seed = 20260728
    enemy = EnemyFeature(content).spawn(enemy_name, seed=seed)
    enemy_attributes = dict(enemy.attributes)
    enemy_attributes.update(
        {
            "血气上限": 156,
            "精神上限": 35,
            "攻击": 3,
            "防御": 7,
            "速度": 102,
            "命中率": 96,
            "暴击率": 5,
        }
    )
    enemy_techniques = enemy.techniques
    enemy_weapon_attack = enemy.weapon_attack
    initial_health = float(player_attributes["血气上限"])
    initial_spirit = float(player_attributes["精神上限"])
    enemy_id = enemy.instance_id

    outcome = engine.simulate(
        left=CombatantSnapshot(
            id="player",
            name="晓楠",
            attributes=player_attributes,
            health=initial_health,
            spirit=initial_spirit,
            weapon_attack=weapon_attack,
            techniques=tuple(techniques),
        ),
        right=CombatantSnapshot(
            id=enemy_id,
            name=enemy_name,
            attributes=enemy_attributes,
            weapon_attack=enemy_weapon_attack,
            techniques=tuple(enemy_techniques),
            level=enemy.level,
            kind=enemy.kind,
        ),
        item_definitions=content.item_definitions,
        seed=seed,
        action_limit=60,
    )

    normalized = build_battle_report(
        outcome,
        (
            BattleReportParticipant(
                id="player",
                name="晓楠",
                title="青岚山散修",
                attributes=outcome.left.attributes,
                initial_health=initial_health,
                final_health=outcome.left.health,
                initial_spirit=initial_spirit,
                final_spirit=outcome.left.spirit,
                initial_shield=0,
                final_shield=outcome.left.shield,
                statuses=outcome.left.statuses,
                techniques=techniques,
                moves=("基础攻击",),
                ability_definitions=content.atomic_ability_definitions,
                level=1,
                kind="修士",
            ),
            BattleReportParticipant(
                id=enemy_id,
                name=enemy_name,
                title="石门遗址守修",
                attributes=outcome.right.attributes,
                initial_health=float(outcome.right.attributes["血气上限"]),
                final_health=outcome.right.health,
                initial_spirit=float(outcome.right.attributes["精神上限"]),
                final_spirit=outcome.right.spirit,
                initial_shield=0,
                final_shield=outcome.right.shield,
                statuses=outcome.right.statuses,
                techniques=tuple(enemy_techniques),
                moves=("基础攻击",),
                ability_definitions=content.atomic_ability_definitions,
                level=enemy.level,
                kind=enemy.kind,
            ),
        ),
        catalog=content.battle_report,
        seed=seed,
        scene="青岚山演武台",
    )
    return build_battle_report_presentation(normalized, content.battle_report)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成晓楠修仙本地战报")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "static" / "battle-report" / "演示战报.json",
    )
    parser.add_argument("--data-output", type=Path)
    args = parser.parse_args()
    report, bundle = generate_report()
    data_output = args.data_output or args.output.with_name(
        f"{args.output.stem}数据.json"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    data_output.parent.mkdir(parents=True, exist_ok=True)
    data_output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"已生成 {args.output}：{report['summary']['title']}，"
        f"{report['detail']['segments'][0]['counts']['actions']} 次行动，"
        f"{report['detail']['segments'][0]['counts']['events']} 条事件；"
        f"明细 {data_output}"
    )


if __name__ == "__main__":
    main()
