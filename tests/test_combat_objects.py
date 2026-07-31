"""功法、附魔与宝石全局实体库的数据契约守卫。"""

from __future__ import annotations

import json
from itertools import combinations_with_replacement
from pathlib import Path
import re
import unittest

from game.rules.battle.executors import EXECUTOR_CATEGORIES
from game.rules.battle.foundation import load_battle_foundation
from game.rules.battle.schema import RuleSchemaValidator


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ITEMS = DATA / "内容" / "物品"
FORBIDDEN_FIELDS = {
    "说明",
    "版本",
    "方向",
    "所属方向",
    "评分",
    "评分模型",
    "职责",
    "提供标签",
    "需要标签",
    "禁止标签",
    "互斥组",
    "随机词条",
    "组成",
}

TECHNIQUE_CATEGORIES = (
    "剑诀", "刀法", "枪法", "拳经", "掌法", "指法", "腿法", "身法", "体术", "心经",
    "炼神秘术", "行气诀", "医经", "毒经", "御灵法", "阵图", "咒法", "天机术", "因果秘典", "禁术",
    "符箓", "雷法", "火法", "水法", "木法", "土法", "音律", "丹诀", "器诀", "祭法",
)
ENCHANTMENT_CATEGORIES = (
    "追锋", "守劫", "截诀", "行气", "状态", "制心",
    "时序", "同契", "御灵", "阵域", "命数", "生灭",
    "雷劫", "众生", "献祭", "返照", "绝境", "断脉", "归墟", "幻法",
)
GEM_FAMILIES = (
    "根基", "命闪", "暴烈", "格挡", "穿透", "攻守",
    "招式", "恢复", "疗愈", "护盾", "控制", "连反",
)
LAYOUTS = {
    ((1, 1, 1), (2,)),
    ((2, 2), (2,)),
    ((2,), (1, 1, 1)),
    ((1, 1), (1, 1, 1)),
    ((2, 1), (1, 1)),
    ((3,), (1, 1)),
}
SIGNATURE_PASSIVES = {
    "600195", "600196", "600881", "600882", "600580", "600585", "601441", "601442",
    "601583", "601581", "600023", "600017", "601284", "600860", "600981", "600156",
    "600297", "600284", "601181", "600904", "601164",
}


def read_groups(directory: Path) -> dict[str, list[dict]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    }


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def references(value, abilities):
    return [
        node["机制"]
        for node in walk(value)
        if isinstance(node.get("能力"), str) and node.get("能力") in abilities
    ]


class CombatObjectLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.technique_groups = read_groups(ITEMS / "功法")
        cls.enchantment_groups = read_groups(ITEMS / "附魔技能书")
        cls.gem_groups = read_groups(ITEMS / "宝石")
        cls.techniques = [value for group in cls.technique_groups.values() for value in group]
        cls.enchantments = [value for group in cls.enchantment_groups.values() for value in group]
        cls.gems = [value for group in cls.gem_groups.values() for value in group]
        cls.rules = load_battle_foundation(DATA)
        cls.validator = RuleSchemaValidator(
            abilities=cls.rules["原子能力"],
            executor_categories=EXECUTOR_CATEGORIES,
            attributes=cls.rules["属性"],
            resources=cls.rules["资源"],
            events=cls.rules["事件"],
            mechanisms=cls.rules["机制"],
        )

    def test_global_libraries_replace_old_direction_copies(self) -> None:
        expected_files = {
            "功法": {f"功法-{category}.json" for category in TECHNIQUE_CATEGORIES},
            "附魔": {f"物品-附魔-{category}.json" for category in ENCHANTMENT_CATEGORIES},
            "宝石": {
                f"物品-宝石-{left if left == right else f'{left}与{right}'}.json"
                for left, right in combinations_with_replacement(GEM_FAMILIES, 2)
            },
        }
        self.assertEqual(set(self.technique_groups), expected_files["功法"])
        self.assertEqual(set(self.enchantment_groups), expected_files["附魔"])
        self.assertEqual(set(self.gem_groups), expected_files["宝石"])
        self.assertTrue(all(len(values) == 20 for values in self.technique_groups.values()))
        self.assertTrue(all(len(values) == 30 for values in self.enchantment_groups.values()))
        self.assertTrue(all(values for values in self.gem_groups.values()))

    def test_ids_start_at_one_and_all_entity_names_are_unique(self) -> None:
        cases = (
            (self.techniques, "40", 600),
            (self.enchantments, "41", 600),
            (self.gems, "42", 703),
        )
        names = []
        for values, prefix, count in cases:
            self.assertEqual(
                {value["编号"] for value in values},
                {f"{prefix}{index:04d}" for index in range(1, count + 1)},
            )
            self.assertTrue(all(set(value) == {"编号", "名称", "权重", "能力"} for value in values))
            names.extend(value["名称"] for value in values)
        self.assertEqual(len(names), len(set(names)))

    def test_entity_weights_are_positive_and_globally_unique(self) -> None:
        values = self.techniques + self.enchantments + self.gems
        weights = [value["权重"] for value in values]
        self.assertTrue(
            all(
                isinstance(weight, int) and not isinstance(weight, bool) and weight > 0
                for weight in weights
            )
        )
        self.assertEqual(len(weights), len(set(weights)))

    def test_formal_entities_have_no_balance_pool_or_legacy_fields(self) -> None:
        for value in self.techniques + self.enchantments + self.gems:
            for node in walk(value):
                self.assertFalse(FORBIDDEN_FIELDS.intersection(node), value["编号"])

    def test_every_ability_tree_matches_the_battle_schema(self) -> None:
        for value in self.techniques + self.enchantments + self.gems:
            for index, ability in enumerate(value["能力"]):
                self.validator.validate_node(
                    ability,
                    f"{value['编号']}.能力[{index}]",
                    allowed_categories={"装配"},
                )

    def test_techniques_are_complete_loops_and_enchantments_are_single_hooks(self) -> None:
        mechanisms = self.rules["机制"]
        layouts = set()
        one_shots = []
        passive_references = set()
        ability_signatures = set()
        mechanism_signatures = set()
        conditional_mysteries = []
        mystery_events = set()
        mystery_relations = set()
        mystery_signatures = set()
        mystery_names = set()
        group_skills = []
        for value in self.techniques:
            self.assertTrue(all(not re.search(r"\d+$", node["名称"]) for node in value["能力"]), value["编号"])
            active = [node for node in value["能力"] if node["能力"] == "主动技能"]
            base_active = [node for node in active if "群体" not in node.get("标签", ())]
            groups = [node for node in active if "群体" in node.get("标签", ())]
            passive = [node for node in value["能力"] if node["能力"] == "被动技能"]
            base_passive = [node for node in passive if node["效果"][0]["能力"] == "引用被动机制"]
            mysteries = [node for node in passive if node["效果"][0]["能力"] == "监听事件"]
            self.assertEqual(value["能力"], active + passive)
            active_refs = [[effect["机制"] for effect in node["效果"]] for node in base_active]
            passive_refs = [[effect["机制"] for effect in node["效果"]] for node in base_passive]
            layouts.add((tuple(map(len, active_refs)), tuple(map(len, passive_refs))))
            flat_active = [identity for group in active_refs for identity in group]
            flat_passive = [identity for group in passive_refs for identity in group]
            ability_signatures.add(json.dumps(value["能力"], ensure_ascii=False, sort_keys=True))
            core_signature = tuple(sorted(references(value, {"引用战斗机制", "引用被动机制"})))
            self.assertNotIn(core_signature, mechanism_signatures, value["编号"])
            mechanism_signatures.add(core_signature)
            passive_references.update(flat_passive)
            self.assertTrue(4 <= len(flat_active) + len(flat_passive) <= 7, value["编号"])
            self.assertTrue(all(mechanisms[identity]["能力"] != "监听事件" for identity in flat_active))
            self.assertTrue(all(mechanisms[identity]["能力"] == "监听事件" for identity in flat_passive))
            for node in base_active:
                if "使用次数" in node:
                    self.assertEqual(node["使用次数"], 1)
                    one_shots.append((value, node))
            for group in groups:
                iterators = [
                    node for node in walk(group)
                    if node.get("能力") == "遍历目标"
                    and node.get("目标", {}).get("选择全部") is True
                    and node.get("目标", {}).get("范围") in {"己方", "敌方"}
                ]
                group_refs = references(group, {"引用战斗机制"})
                self.assertEqual(len(iterators), 1)
                self.assertEqual(len(group_refs), 1)
                self.assertTrue(all(mechanisms[identity]["能力"] != "监听事件" for identity in group_refs))
                group_skills.append((value, group, iterators[0]["目标"]["范围"]))
            for mystery in mysteries:
                listener = mystery["效果"][0]
                payoff_refs = references(listener, {"引用战斗机制"})
                self.assertEqual(listener.get("每场战斗最多触发"), 1)
                self.assertEqual(len(payoff_refs), 2)
                self.assertTrue(all(mechanisms[identity]["能力"] != "监听事件" for identity in payoff_refs))
                conditional_mysteries.append((value, mystery))
                mystery_events.add(listener["事件"])
                mystery_relations.add(listener["阵营关系"])
                mystery_names.add(mystery["名称"].rsplit("·", 1)[-1])
                mystery_signatures.add((
                    listener["事件"], listener.get("观察角色", "来源"),
                    listener["阵营关系"], tuple(payoff_refs),
                ))

        self.assertTrue(LAYOUTS <= layouts)
        self.assertEqual(len(ability_signatures), 600)
        self.assertEqual(len(mechanism_signatures), 600)
        self.assertEqual(len(one_shots), 124)
        self.assertEqual(len(group_skills), 120)
        self.assertEqual(
            {category: sum(value in values for value, _, _ in group_skills) for category, values in self.technique_groups.items()},
            {category: 4 for category in self.technique_groups},
        )
        self.assertEqual({scope for _, _, scope in group_skills}, {"己方", "敌方"})
        self.assertEqual(len(conditional_mysteries), 40)
        self.assertEqual(len(mystery_names), 40)
        self.assertEqual(len(mystery_signatures), 40)
        self.assertGreaterEqual(len(mystery_events), 20)
        self.assertEqual(mystery_relations, {"自身", "其他己方", "任意敌方"})
        self.assertTrue(SIGNATURE_PASSIVES <= passive_references)

        for value in self.enchantments:
            self.assertFalse(re.search(r"\d+$", value["名称"]), value["编号"])
            self.assertFalse(
                any(word in value["名称"] for word in ("技能", "事件", "事务", "计量", "全队", "群敌", "加税", "可撤")),
                value["编号"],
            )
            self.assertEqual(len(value["能力"]), 1)
            passive = value["能力"][0]
            self.assertEqual(passive["能力"], "被动技能")
            self.assertEqual(len(passive["效果"]), 1)
            reference = passive["效果"][0]
            self.assertEqual(reference["能力"], "引用被动机制")
            self.assertEqual(mechanisms[reference["机制"]]["能力"], "监听事件")
        self.assertEqual(
            len({value["能力"][0]["效果"][0]["机制"] for value in self.enchantments}),
            600,
        )

    def test_gems_are_distinct_fixed_attributes_and_cover_the_attribute_table(self) -> None:
        shapes = set()
        covered = set()
        singles = set()
        pairs = set()
        for value in self.gems:
            self.assertNotIn("·", value["名称"])
            self.assertEqual(len(value["能力"]), 1)
            ability = value["能力"][0]
            self.assertEqual(ability["能力"], "固定属性加成")
            attributes = ability["属性"]
            covered.update(attributes)
            shapes.add(json.dumps(attributes, ensure_ascii=False, sort_keys=True))
            keys = tuple(sorted(attributes))
            self.assertIn(len(keys), {1, 2})
            (singles if len(keys) == 1 else pairs).add(keys)
        self.assertEqual(len(shapes), 703)
        self.assertEqual(covered, set(self.rules["属性"]))
        self.assertEqual(len(singles), 37)
        self.assertEqual(len(pairs), 666)


if __name__ == "__main__":
    unittest.main()
