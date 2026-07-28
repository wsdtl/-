from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from game.content import GameContent
from game.core import JsonDataReader
from game.features.diren import EnemyFeature
from game.rules import BattleEngine, CombatantSnapshot
from game.rules.battle import (
    BattleReportCatalog,
    BattleReportParticipant,
    build_battle_report,
    build_battle_report_presentation,
)


ROOT = Path(__file__).resolve().parents[1]


class BattleReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.content = GameContent.load(JsonDataReader(ROOT / "data"))

    def test_report_uses_backend_actor_colors_and_enemy_final_state(self) -> None:
        technique_definition = self.content.technique_definitions["离火归元诀"]
        technique = {
            "实例": "report-test-1",
            "功法": "离火归元诀",
            "品级": "凡品",
            "出生序号": 1,
            "威力倍率": 1.0,
            "词条": [],
            "能力": [dict(value) for value in technique_definition["组成"]],
        }
        player_attributes = dict(self.content.player["人物"]["属性"])
        seed = 71
        enemy = EnemyFeature(self.content).spawn("山道劫修", seed=seed)
        enemy_id = enemy.instance_id
        enemy_techniques = enemy.techniques
        outcome = BattleEngine(self.content.combat).simulate(
            left=CombatantSnapshot(
                id="player",
                name="甲",
                attributes=player_attributes,
                health=100,
                spirit=60,
                weapon_attack=10,
                techniques=(technique,),
            ),
            right=enemy.battle_snapshot(),
            item_definitions=self.content.item_definitions,
            seed=seed,
            action_limit=30,
        )
        report = build_battle_report(
            outcome,
            (
                BattleReportParticipant(
                    "player",
                    "甲",
                    "修士",
                    {**player_attributes, "攻击": player_attributes["攻击"] + 10},
                    100,
                    outcome.left.health,
                    60,
                    outcome.left.spirit,
                    statuses=outcome.left.statuses,
                    techniques=(technique,),
                    ability_definitions=self.content.atomic_ability_definitions,
                    level=1,
                    kind="修士",
                ),
                BattleReportParticipant(
                    enemy_id,
                    enemy.enemy_id,
                    "敌方",
                    outcome.right.attributes,
                    outcome.right.attributes["血气上限"],
                    outcome.right.health,
                    initial_spirit=outcome.right.attributes["精神上限"],
                    final_spirit=outcome.right.spirit,
                    statuses=outcome.right.statuses,
                    techniques=tuple(enemy_techniques),
                    moves=("基础攻击",),
                    ability_definitions=self.content.atomic_ability_definitions,
                    level=enemy.level,
                    kind=enemy.kind,
                ),
            ),
            catalog=self.content.battle_report,
            seed=seed,
            generated_at="2026-07-28T12:00:00+08:00",
        )

        self.assertEqual(report["schema"], "晓楠修仙.战报.v1")
        self.assertEqual(report["participants"][1]["resources"][0]["current"], outcome.right.health)
        colors = {value["id"]: value["color"] for value in report["participants"]}
        self.assertEqual(colors["player"], self.content.battle_report.participant_colors[0])
        self.assertEqual(colors[enemy_id], self.content.battle_report.participant_colors[1])
        self.assertNotEqual(colors["player"], colors[enemy_id])
        self.assertEqual(report["participants"][1]["level"], enemy.level)
        self.assertEqual(report["participants"][1]["kind"], "修士")
        for event in report["events"]:
            if event["kind"] in {"战斗开始", "战斗结束"}:
                self.assertEqual(event["source"]["id"], "system")
            elif event["source"]["id"] in colors:
                self.assertEqual(event["source"]["color"], colors[event["source"]["id"]])
        damage = next(event for event in report["events"] if event["kind"] == "damage")
        self.assertTrue(damage["steps"])
        self.assertTrue(any(item["label"] == "命中判定值" for item in damage["details"]))
        self.assertEqual(
            sum(item["count"] for item in report["filters"] if item["id"] != "all"),
            len(report["events"]),
        )

        presentation, bundle = build_battle_report_presentation(
            report,
            self.content.battle_report,
        )
        self.assertEqual(presentation["schema"], "game.battle_report.presentation")
        self.assertEqual(presentation["version"], 3)
        self.assertEqual(presentation["game_name"], "晓楠修仙")
        self.assertEqual(presentation["ui"], self.content.battle_report.ui)
        self.assertEqual(
            presentation["detail"]["segments"][0]["combatants"][0]["visual"]["color"],
            report["participants"][0]["color"],
        )
        self.assertIn(
            f"Lv{enemy.level}",
            presentation["detail"]["segments"][0]["initial_participants"][1]["team_label"],
        )
        self.assertIn("0", bundle["events"])
        self.assertIn("0:before", bundle["participants"])
        self.assertIn("0:after", bundle["participants"])
        self.assertTrue(bundle["transitions"])
        self.assertEqual(bundle["raw"]["0"]["record"]["schema"], "晓楠修仙.战报.v1")

    def test_report_catalog_rejects_invalid_visual_configuration(self) -> None:
        raw = deepcopy(dict(self.content.battle_report.raw))
        raw["视觉"]["参战者颜色"] = ["red"]
        with self.assertRaisesRegex(ValueError, "战报颜色不合法"):
            BattleReportCatalog.from_mapping(raw)


if __name__ == "__main__":
    unittest.main()
