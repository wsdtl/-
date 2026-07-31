from __future__ import annotations

from pathlib import Path
import unittest

from game.content_loading import load_game_data
from game.rules.loadout import compatibility_issues, mechanism_references


ROOT = Path(__file__).resolve().parents[1]


class LoadoutRuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loaded = load_game_data(ROOT / "data")
        cls.mechanisms = cls.loaded.entities["机制"]
        cls.rules = cls.loaded.catalog.read("规则/战斗/构筑.json")

    def test_entities_are_checked_by_recursive_mechanism_reference(self) -> None:
        entity = {
            "编号": "test",
            "名称": "试制法门",
            "能力": [
                {
                    "能力": "主动技能",
                    "效果": [
                        {"能力": "引用战斗机制", "机制": "600033"},
                        {"能力": "引用战斗机制", "机制": "600032"},
                    ],
                }
            ],
        }
        self.assertEqual(
            mechanism_references(entity, self.mechanisms),
            frozenset({"600032", "600033"}),
        )
        issues = compatibility_issues(
            {"功法": (("test", entity),)},
            mechanisms=self.mechanisms,
            conflicts=self.rules["相冲"],
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("阴阳逆流", issues[0])

    def test_formal_entities_do_not_carry_compatibility_metadata(self) -> None:
        forbidden = {"提供标签", "需要标签", "禁止标签", "互斥组"}
        for kind in ("功法", "附魔", "宝石"):
            for definition in self.loaded.entities[kind].values():
                self.assertFalse(forbidden.intersection(definition))

    def test_conflict_names_are_unique_cultivation_names(self) -> None:
        names = [str(value["名称"]) for value in self.rules["相冲"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all("." not in name and ":" not in name for name in names))


if __name__ == "__main__":
    unittest.main()
