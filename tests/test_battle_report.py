from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from game.content import GameContent
from game.core import JsonDataReader
from game.rules import BattleEngine, CombatantSnapshot
from game.rules.battle import (
    BattleReportCatalog,
    BattleReportParticipant,
    build_battle_report,
    build_battle_report_presentation,
)


ROOT = Path(__file__).resolve().parents[1]


def _opponent(attributes: dict[str, float], *, identity: str = "report-enemy") -> CombatantSnapshot:
    opponent_attributes = {
        **attributes,
        "血气上限": 140,
        "精神上限": 40,
        "攻击": 7,
        "防御": 3,
        "速度": 90,
    }
    return CombatantSnapshot(
        id=identity,
        name="试剑傀儡",
        attributes=opponent_attributes,
        health=140,
        spirit=40,
        weapon_attack=8,
        level=1,
        kind="傀儡",
    )


class BattleReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.content = GameContent.load(JsonDataReader(ROOT / "data"))

    def test_report_uses_backend_actor_colors_and_enemy_final_state(self) -> None:
        technique_id = next(
            technique_id
            for technique_id, definition in self.content.technique_definitions.items()
            if any(
                self.content.ability_executor(dict(node)) == "装配主动技能"
                for node in definition["能力"]
            )
        )
        technique = self.content.configured_battle_techniques(
            [{"编号": technique_id, "品级": "01"}],
            instance_prefix="report-test",
        )[0]
        player_attributes = dict(self.content.player["人物"]["属性"])
        seed = 71
        enemy = _opponent(player_attributes)
        enemy_id = enemy.id
        outcome = BattleEngine(self.content.combat).simulate(
            left=CombatantSnapshot(
                id="player",
                name="甲",
                attributes=player_attributes,
                health=100,
                spirit=60,
                weapon_attack=10,
                techniques=(),
            ),
            right=enemy,
            item_definitions={},
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
                    enemy.name,
                    "敌方",
                    outcome.right.attributes,
                    outcome.right.attributes["血气上限"],
                    outcome.right.health,
                    initial_spirit=outcome.right.attributes["精神上限"],
                    final_spirit=outcome.right.spirit,
                    statuses=outcome.right.statuses,
                    techniques=enemy.techniques,
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
        self.assertEqual(report["participants"][1]["kind"], enemy.kind)
        self.assertNotIn("affixes", report["participants"][0]["techniques"][0])
        for event in report["events"]:
            if event["kind"] in {"战斗开始", "战斗结束"}:
                self.assertEqual(event["source"]["id"], "system")
            elif event["source"]["id"] in colors:
                self.assertEqual(event["source"]["color"], colors[event["source"]["id"]])
        self.assertTrue(report["events"])
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

    def test_team_battle_report_keeps_every_participant(self) -> None:
        attributes = dict(self.content.player["人物"]["属性"])
        left = (
            CombatantSnapshot(
                id="player",
                name="甲",
                attributes=attributes,
                weapon_attack=10,
            ),
            CombatantSnapshot(
                id="partner:宁药师",
                name="宁药师",
                attributes={**attributes, "攻击": 4, "防御": 3},
                weapon_attack=10,
                kind="道侣",
            ),
        )
        right = (_opponent(attributes, identity="team-enemy"),)
        outcome = BattleEngine(self.content.combat).simulate_teams(
            left=left,
            right=right,
            item_definitions={},
            seed=19,
            action_limit=30,
        )
        snapshots = {value.id: value for value in (*left, *right)}
        participants = tuple(
            BattleReportParticipant(
                result.id,
                result.name,
                "我方" if result.id in {value.id for value in left} else "敌方",
                result.attributes,
                float(result.attributes["血气上限"]),
                result.health,
                float(result.attributes["精神上限"]),
                result.spirit,
                statuses=result.statuses,
                techniques=tuple(snapshots[result.id].techniques),
                ability_definitions=self.content.atomic_ability_definitions,
                level=result.level,
                kind=result.kind,
            )
            for result in (*outcome.left_results, *outcome.right_results)
        )
        report = build_battle_report(
            outcome,
            participants,
            catalog=self.content.battle_report,
            seed=19,
            generated_at="2026-07-29T12:00:00+08:00",
        )
        self.assertEqual(len(report["participants"]), 3)
        self.assertIn("甲、宁药师 对阵", report["headline"])
        self.assertEqual(
            len({value["color"] for value in report["participants"]}),
            3,
        )
        presentation, bundle = build_battle_report_presentation(
            report,
            self.content.battle_report,
        )
        self.assertEqual(len(presentation["detail"]["segments"][0]["combatants"]), 3)
        self.assertEqual(len(bundle["participants"]["0:before"]["participants"]), 3)


if __name__ == "__main__":
    unittest.main()
