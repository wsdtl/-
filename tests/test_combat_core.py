from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import random
import shutil
from tempfile import TemporaryDirectory
import unittest

from game.app import build_game_services
from game.cmd.地点.service import _append_function_commands
from game.cmd.功法.service import _mechanism_text
from game.content import GameContent, GameContentError, _validate
from game.core import JsonDataReader
from game.features.diren import EnemyFeature
from game.features.loadout import direction_candidates, roll_loadout
from game.rules import BattleEngine, CombatantSnapshot
from game.rules.battle import BattleContext, DamageRequest, Fighter
from game.rules.loadout import compatibility_issues
from message import CommandLink, M


ROOT = Path(__file__).resolve().parents[1]


class FixedRandom:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)

    def random(self) -> float:
        return next(self.values)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> str:
        return self.value.isoformat(timespec="seconds")

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class CombatCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.content = GameContent.load(JsonDataReader(ROOT / "data"))
        cls.engine = BattleEngine(cls.content.combat)
        cls.enemies = EnemyFeature(cls.content)
        cls.player_attributes = dict(cls.content.player["人物"]["属性"])
        cls.sample_technique_group, techniques = next(
            iter(cls.content.technique_groups.items())
        )
        cls.sample_direction = cls.content.technique_group_directions[
            cls.sample_technique_group
        ]
        cls.sample_active_techniques = tuple(
            technique_id
            for technique_id in techniques
            if cls.content.technique_definitions[technique_id]["职责"] == "主动"
        )
        cls.sample_passive_techniques = tuple(
            technique_id
            for technique_id in techniques
            if cls.content.technique_definitions[technique_id]["职责"] == "被动"
        )
        cls.sample_enchantment_group = next(
            group_id
            for group_id, direction_id in cls.content.enchantment_group_directions.items()
            if direction_id == cls.sample_direction
        )
        cls.sample_gem_group = next(
            group_id
            for group_id, direction_id in cls.content.gem_group_directions.items()
            if direction_id == cls.sample_direction
        )
        cls.sample_enchantments = cls.content.enchantment_groups[
            cls.sample_enchantment_group
        ]
        cls.sample_gems = cls.content.gem_groups[cls.sample_gem_group]

    def fighter(
        self,
        fighter_id: str,
        *,
        health: float = 100,
        shield: float = 0,
        **attributes: float,
    ) -> Fighter:
        values = {
            "血气上限": max(health, 100),
            "精神上限": 60,
            "攻击": 10,
            "命中率": 100,
            "暴击率": 0,
            "暴击伤害": 150,
            "格挡率": 0,
            "格挡减伤": 0,
            "护盾上限": max(shield, 0),
        }
        values.update(attributes)
        return Fighter(fighter_id, fighter_id, values, health, 0, shield)

    def context(
        self,
        player: Fighter,
        enemy: Fighter,
        *,
        passives: tuple[dict, ...] = (),
    ) -> BattleContext:
        player.passives = tuple(
            {
                **value,
                "结算顺序": int(value.get("结算顺序") or 900000 + index),
            }
            for index, value in enumerate(passives, start=1)
        )
        context = BattleContext(
            rng=random.Random(7),
            left=player,
            right=enemy,
            item_definitions={},
        )
        context.engine = self.engine
        context.action_progress = {player.id: 0.0, enemy.id: 0.0}
        return context

    def technique(self, name: str, born_order: int) -> dict:
        definition = self.content.technique_definitions[name]
        return {
            "实例": f"test-{born_order}",
            "功法": name,
            "品级": "黄品",
            "出生序号": born_order,
            "威力倍率": 1.0,
            "词条": [],
            "能力": [dict(value) for value in definition.get("组成") or ()],
        }

    @staticmethod
    def active_technique(
        name: str,
        mechanism: str,
        *,
        release_order: int = 990001,
    ) -> dict:
        return {
            "实例": f"test-active:{name}",
            "功法": name,
            "品级": "黄品",
            "出生序号": 1,
            "威力倍率": 1.0,
            "词条": [],
            "能力": [
                {
                    "能力": "主动技能",
                    "名称": name,
                    "释放顺序": release_order,
                    "精神消耗": 0,
                    "冷却回合": 0,
                    "效果": [{"能力": "引用战斗机制", "机制": mechanism}],
                }
            ],
        }

    def enemy_snapshot(
        self,
        enemy_id: str,
        seed: int,
        *,
        content: GameContent | None = None,
        definition: dict | None = None,
    ) -> CombatantSnapshot:
        configured = content or self.content
        opponent = definition or configured.enemy_definitions[enemy_id]
        level = int(opponent["等级"][0])
        growth = (
            configured.player["人物"]["每级成长"]
            if opponent["类别"] == "修士"
            else opponent["每级成长"]
        )
        return CombatantSnapshot(
            id=f"opponent:{seed}",
            name=enemy_id,
            attributes=configured.attributes_at_level(opponent["属性"], growth, level),
            level=level,
            kind=str(opponent["类别"]),
            weapon_attack=float((opponent.get("本命武器") or {}).get("攻击") or 0),
            techniques=tuple(
                configured.configured_battle_techniques(
                    opponent.get("功法") or [],
                    instance_prefix=f"opponent:{seed}",
                )
            ),
            medicine_threshold=float(
                (opponent.get("战斗策略") or {}).get("用药阈值") or 0.3
            ),
        )

    def simulate(
        self,
        techniques: list[str] | None = None,
        *,
        seed: int = 12345,
        action_limit: int = 80,
        statuses: list[dict] | None = None,
        rules: BattleEngine | None = None,
        attributes: dict[str, float] | None = None,
        enemy: dict | None = None,
        enemy_id: str = "山道劫修",
        spirit: float = 60,
    ):
        names = techniques or []
        opponent = enemy or self.content.enemy_definitions[enemy_id]
        return (rules or self.engine).simulate(
            left=CombatantSnapshot(
                id="player",
                name="测试修士",
                attributes=attributes or self.player_attributes,
                health=100,
                spirit=spirit,
                statuses=tuple(statuses or ()),
                weapon_attack=10,
                techniques=tuple(
                    self.technique(name, index + 1)
                    for index, name in enumerate(names)
                ),
            ),
            right=self.enemy_snapshot(
                enemy_id,
                seed,
                definition=opponent,
            ),
            item_definitions=self.content.combat_item_definitions(),
            seed=seed,
            action_limit=action_limit,
        )

    def test_damage_pipeline_and_boundaries(self) -> None:
        source = self.fighter(
            "source",
            **{
                "暴击率": 100,
                "暴击伤害": 200,
                "比例穿透": 50,
                "固定穿透": 10,
                "伤害加成": 20,
            },
        )
        target = self.fighter(
            "target",
            health=50,
            shield=30,
            **{"防御": 40, "伤害减免": 10, "格挡率": 100, "格挡减伤": 50},
        )
        result = self.engine.damage.resolve(
            DamageRequest(100, "验算", can_miss=True),
            source=source,
            target=target,
            rng=FixedRandom(0, 0, 0),
        )
        self.assertTrue(result.hit)
        self.assertTrue(result.critical)
        self.assertTrue(result.blocked)
        self.assertAlmostEqual(result.breakdown.effective_defense, 10)
        self.assertAlmostEqual(result.breakdown.after_rates, 200)
        self.assertAlmostEqual(result.breakdown.after_block, 100)
        self.assertEqual(result.shield_damage, 30)
        self.assertEqual(result.health_damage, 50)
        self.assertAlmostEqual(result.overkill, 20)
        self.assertTrue(result.defeated)

        missed = self.engine.damage.resolve(
            DamageRequest(10, "落空", can_miss=True, can_critical=False, can_block=False),
            source=self.fighter("miss", **{"命中率": 0}),
            target=self.fighter("evade"),
            rng=FixedRandom(0.9),
        )
        self.assertFalse(missed.hit)
        self.assertEqual(missed.actual_damage, 0)

        no_critical = self.engine.damage.resolve(
            DamageRequest(10, "抗暴", can_miss=False, can_block=False),
            source=source,
            target=self.fighter("anti", **{"抗暴率": 100}),
            rng=FixedRandom(0),
        )
        self.assertFalse(no_critical.critical)

        not_blocked = self.engine.damage.resolve(
            DamageRequest(10, "破格", can_miss=False, can_critical=False),
            source=self.fighter("breaker", **{"破格率": 100}),
            target=self.fighter("blocker", **{"格挡率": 100, "格挡减伤": 90}),
            rng=FixedRandom(0),
        )
        self.assertFalse(not_blocked.blocked)

        true_damage = self.engine.damage.resolve(
            DamageRequest(25, "真实", defense_rule="真实"),
            source=self.fighter("true-source"),
            target=self.fighter(
                "true-target",
                **{"防御": 1000, "伤害减免": 90, "格挡率": 100, "格挡减伤": 90},
            ),
            rng=FixedRandom(0),
        )
        self.assertEqual(true_damage.actual_damage, 25)
        self.assertFalse(true_damage.blocked)

    def test_content_rejects_unknown_fields_and_unimplemented_abilities(self) -> None:
        combat = deepcopy(self.content.combat)
        combat["机制"]["真火击"]["能否暴机"] = True
        with self.assertRaisesRegex(GameContentError, "能否暴机"):
            _validate(replace(self.content, combat=combat))

        combat = deepcopy(self.content.combat)
        combat["机制"]["错误时空"] = {"能力": "逆转时空"}
        with self.assertRaisesRegex(GameContentError, "未知原子能力 逆转时空"):
            _validate(replace(self.content, combat=combat))

        combat = deepcopy(self.content.combat)
        combat["原子能力"]["空壳能力"] = {
            "类别": "效果",
            "执行器": "尚不存在的执行器",
            "说明": "不能只靠写 JSON 假装底层语义已经实现。",
            "字段": {},
        }
        with self.assertRaisesRegex(GameContentError, "没有执行器 尚不存在的执行器"):
            _validate(replace(self.content, combat=combat))

    def test_classified_directories_expand_and_reject_duplicate_names(self) -> None:
        self.assertEqual(
            self.content.enemy_groups["青溪村敌人"],
            ("青溪村黄鬃山獾", "灰翼石蝠"),
        )
        self.assertEqual(
            self.content.enemy_groups["朔风原敌人"],
            ("朔风原石门守修", "朔风原山道劫修"),
        )
        self.assertEqual(
            self.content.npc_groups["青溪村道侣"],
            ("沈昭宁", "沈听澜", "沈星遥"),
        )
        self.assertEqual(
            self.content.enemies_in_groups(["青溪村敌人", "朔风原敌人"]),
            (
                "青溪村黄鬃山獾",
                "灰翼石蝠",
                "朔风原石门守修",
                "朔风原山道劫修",
            ),
        )
        self.assertEqual(
            set(self.content.enemy_group_kinds.values()),
            {"敌对修士", "灵兽"},
        )
        for location_id in ("朔风原", "寒雾林", "黑石岭", "裂天原"):
            self.assertEqual(
                self.content.location_definitions[location_id]["道侣池"],
                [],
            )
        self.assertEqual(
            self.content.location_definitions["青溪村"]["可用功能"],
            ["闭关", "修士", "探险"],
        )
        reply = M.document().section("地点")
        _append_function_commands(reply, ("闭关", "修士", "探险"))
        commands = [
            span
            for block in reply.build().document.blocks
            for line in block.lines
            for span in line
            if isinstance(span, CommandLink)
        ]
        self.assertEqual(
            [(command.command, command.submit) for command in commands],
            [("闭关", True), ("修士", True), ("探险", True)],
        )
        self.assertTrue(
            all(
                "安全地点" not in definition
                for definition in self.content.location_definitions.values()
            )
        )
        world = deepcopy(self.content.world)
        world["地点"]["朔风原"]["道侣池"] = ["青溪村道侣"]
        with self.assertRaisesRegex(GameContentError, "必须先在可用功能中启用修士"):
            _validate(replace(self.content, world=world))

        world = deepcopy(self.content.world)
        world["地点"]["青溪村"]["敌人池"].append("朔风原敌人")
        with self.assertRaisesRegex(GameContentError, "探险敌人必须按地点放入"):
            _validate(replace(self.content, world=world))

        with TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            shutil.copytree(ROOT / "data" / "rules", data_dir / "rules")
            shutil.copytree(ROOT / "data" / "content", data_dir / "content")
            duplicate = {
                "版本": "测试.重复功法.v1",
                "战斗方向": {
                    **deepcopy(self.content.direction_definitions[self.sample_direction]),
                    "名称": "重复功法测试方向",
                },
                "功法": {
                    self.sample_active_techniques[0]: deepcopy(
                        self.content.technique_definitions[
                            self.sample_active_techniques[0]
                        ]
                    )
                },
            }
            (data_dir / "content" / "物品" / "功法" / "重复功法.json").write_text(
                json.dumps(duplicate, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                GameContentError,
                f"{self.sample_active_techniques[0]}.*重名",
            ):
                GameContent.load(JsonDataReader(data_dir))

        with TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            shutil.copytree(ROOT / "data" / "rules", data_dir / "rules")
            shutil.copytree(ROOT / "data" / "content", data_dir / "content")
            (
                data_dir
                / "content"
                / "世界"
                / "青岚州"
                / "青溪村"
                / "青溪村敌人.json"
            ).write_text(
                json.dumps(
                    {"版本": "测试.空池.v1", "敌人": {}},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GameContentError, "青溪村敌人.json 资源池不能为空"):
                GameContent.load(JsonDataReader(data_dir))

        with TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            shutil.copytree(ROOT / "data" / "rules", data_dir / "rules")
            shutil.copytree(ROOT / "data" / "content", data_dir / "content")
            source_name = f"{self.sample_technique_group}.json"
            shutil.copyfile(
                data_dir / "content" / "物品" / "功法" / source_name,
                data_dir / "content" / "战斗机制" / source_name,
            )
            with self.assertRaisesRegex(
                GameContentError,
                f"JSON 文件名重复 {source_name}",
            ):
                GameContent.load(JsonDataReader(data_dir))

    def test_integrated_pools_use_inverse_integer_weights(self) -> None:
        enemy_pool = self.content.enemies_in_groups(["青溪村敌人"])
        self.assertIn(
            self.content.choose_enemy(enemy_pool, FixedRandom(0.5, 0.5, 0.5)),
            enemy_pool,
        )
        npc_pool = self.content.npcs_in_groups(["青溪村道侣"])
        self.assertIn(
            self.content.choose_npc(npc_pool, FixedRandom(0.5, 0.5, 0.5)),
            npc_pool,
        )
        self.assertEqual(
            self.content.choose_item(
                ("小还丹", "草原灵矿"),
                FixedRandom(0.5, 0.5),
            ),
            "小还丹",
        )
        technique_candidates = self.sample_active_techniques[:2]
        self.assertEqual(
            self.content.choose_technique(
                technique_candidates,
                FixedRandom(0.5, 0.5),
            ),
            min(
                technique_candidates,
                key=lambda value: self.content.technique_definitions[value]["权重"],
            ),
        )
        gem_candidates = self.sample_gems[:2]
        self.assertEqual(
            self.content.choose_gem(
                gem_candidates,
                FixedRandom(0.5, 0.5),
            ),
            min(
                gem_candidates,
                key=lambda value: self.content.gem_definitions[value]["权重"],
            ),
        )

        for definitions in (
            self.content.npc_definitions,
            self.content.enemy_definitions,
            self.content.item_definitions,
            self.content.technique_definitions,
            self.content.grade_definitions,
            self.content.affix_definitions,
            self.content.enchantment_definitions,
            self.content.gem_definitions,
        ):
            self.assertTrue(
                all(
                    isinstance(definition["权重"], int)
                    and not isinstance(definition["权重"], bool)
                    and definition["权重"] >= 1
                    for definition in definitions.values()
                )
            )

        items = deepcopy(self.content.items)
        items["物品"]["小还丹"]["权重"] = 0.5
        with self.assertRaisesRegex(GameContentError, "小还丹.权重.*必须是整数"):
            _validate(replace(self.content, items=items))

    def test_content_foundation_has_classified_items_and_partner_pools(self) -> None:
        self.assertTrue(
            {
                "物品-丹药-恢复血气",
                "物品-丹药-恢复精神",
                "物品-修行器物-人物经验",
                "物品-修行器物-本命武器经验",
                "物品-修行器物-道侣经验",
            }.issubset(self.content.item_groups)
        )
        category_counts = Counter(
            str(definition["类别"])
            for definition in self.content.item_definitions.values()
        )
        for category, minimum in {
            "丹药": 6,
            "附魔技能书": 1,
            "宝石": 1,
            "天材地宝": 108,
            "修行器物": 3,
        }.items():
            self.assertGreaterEqual(category_counts[category], minimum)

        enchantment_items = {
            str(definition["对应附魔"])
            for definition in self.content.item_definitions.values()
            if definition["类别"] == "附魔技能书"
        }
        gem_items = {
            str(definition["对应宝石"])
            for definition in self.content.item_definitions.values()
            if definition["类别"] == "宝石"
        }
        self.assertEqual(enchantment_items, set(self.content.enchantment_definitions))
        self.assertEqual(gem_items, set(self.content.gem_definitions))

        self.assertEqual(
            sum(group_id.startswith("物品-附魔-") for group_id in self.content.enchantment_groups),
            264,
        )
        self.assertEqual(
            sum(group_id.startswith("物品-宝石-") for group_id in self.content.gem_groups),
            264,
        )
        for npc_id in self.content.npc_definitions:
            candidates = self.content.npc_loadout_candidates(npc_id)
            self.assertEqual(len(candidates["功法"]), 9)
            self.assertEqual(len(candidates["附魔"]), 9)
            self.assertEqual(len(candidates["宝石"]), 9)

        enchantment_item = next(
            item_id
            for item_id, definition in self.content.item_definitions.items()
            if definition["类别"] == "附魔技能书"
        )
        items = deepcopy(self.content.items)
        items["物品"][enchantment_item]["对应附魔"] = "不存在的附魔"
        with self.assertRaisesRegex(
            GameContentError,
            f"{enchantment_item}.对应附魔.*不存在",
        ):
            _validate(replace(self.content, items=items))

    def test_generated_catalog_has_unique_json_names_and_valid_slot_loadouts(self) -> None:
        json_files = tuple((ROOT / "data" / "content").rglob("*.json"))
        duplicate_names = {
            name: count
            for name, count in Counter(path.name for path in json_files).items()
            if count > 1
        }
        self.assertFalse(duplicate_names)

        definitions = {
            "功法": self.content.technique_definitions,
            "附魔": self.content.enchantment_definitions,
            "宝石": self.content.gem_definitions,
        }
        for direction_index, direction_id in enumerate(
            sorted(self.content.direction_definitions),
            start=1,
        ):
            candidates = direction_candidates(self.content, direction_id)
            for slot in (3, 6):
                loadout = roll_loadout(
                    self.content,
                    random.Random(direction_index * 10 + slot),
                    candidates=candidates,
                    counts={kind: slot for kind in ("功法", "附魔", "宝石")},
                    direction_id=direction_id,
                    grade_id="黄品",
                )
                selected = {
                    "功法": tuple(
                        (
                            str(value["功法"]),
                            definitions["功法"][str(value["功法"])],
                        )
                        for value in loadout.techniques
                    ),
                    "附魔": tuple(
                        (
                            str(value["名称"]),
                            definitions["附魔"][str(value["名称"])],
                        )
                        for value in loadout.enchantments
                    ),
                    "宝石": tuple(
                        (
                            str(value["名称"]),
                            definitions["宝石"][str(value["名称"])],
                        )
                        for value in loadout.gems
                    ),
                }
                role_rule = self.content.combination_rules["功法职责"][str(slot)]
                self.assertFalse(
                    compatibility_issues(
                        selected,
                        active_minimum=int(role_rule["主动最少"]),
                        passive_minimum=int(role_rule["被动最少"]),
                    ),
                    f"{direction_id}的{slot}槽构筑不合法",
                )

    def test_player_weapon_augments_enter_exploration_battle(self) -> None:
        with TemporaryDirectory() as directory:
            services = build_game_services(
                data_dir=ROOT / "data",
                database_path=Path(directory) / "game.db",
            )
            user_id = "player-augment-battle"
            services.player.ensure(user_id, "兵纹测试")
            self.assertEqual(services.location.move(user_id, "朔风原").status, "moved")
            enchantment_id = self.sample_enchantments[0]
            gem_id = self.sample_gems[0]
            with services.database.transaction(write=True) as connection:
                weapon = services.player.load_weapon_in_connection(connection, user_id)
                weapon.enchantments = [{"名称": enchantment_id, "品级": "玄品"}]
                weapon.gems = [{"名称": gem_id, "品级": "地品"}]
                services.player.update_weapon_in_connection(connection, weapon)

            captured: list[tuple[dict, ...]] = []
            battle = services.exploration.battle

            class BattleCapture:
                def simulate_teams(self, **kwargs):
                    captured.append(tuple(kwargs["left"][0].techniques))
                    return battle.simulate_teams(**kwargs)

            services.exploration.battle = BattleCapture()
            services.exploration.seed_factory = lambda: 17
            self.assertEqual(services.exploration.start(user_id).status, "started")
            self.assertTrue(captured)
            player_loadout = captured[0]
            self.assertIn(
                ("附魔", enchantment_id, "玄品"),
                {
                    (value.get("类型"), value.get("名称"), value.get("品级"))
                    for value in player_loadout
                },
            )
            self.assertIn(
                ("宝石", gem_id, "地品"),
                {
                    (value.get("类型"), value.get("名称"), value.get("品级"))
                    for value in player_loadout
                },
            )

    def test_new_enchantment_passive_executes_from_json(self) -> None:
        enchantment_id = self.sample_enchantments[0]
        enchantment = self.content.configured_weapon_augment(
            "附魔",
            enchantment_id,
            "黄品",
            instance_id="enchantment:iron-bone",
        )
        passive = next(
            value for value in enchantment["能力"] if value["能力"] == "被动技能"
        )
        mechanism_id = passive["效果"][0]["机制"]
        left_attributes = dict(self.player_attributes)
        left_attributes["速度"] = 200
        right_attributes = dict(self.player_attributes)
        right_attributes.update({"血气上限": 500, "速度": 1})
        outcome = self.engine.simulate(
            left=CombatantSnapshot(
                id="left",
                name="甲",
                attributes=left_attributes,
                health=100,
                spirit=60,
                techniques=(enchantment,),
            ),
            right=CombatantSnapshot(
                id="right",
                name="乙",
                attributes=right_attributes,
                health=500,
                spirit=60,
            ),
            item_definitions=self.content.combat_item_definitions(),
            seed=7,
            action_limit=1,
        )
        self.assertTrue(any(event.mechanism == mechanism_id for event in outcome.events))

    def test_every_enchantment_group_can_enter_combat(self) -> None:
        left_attributes = dict(self.player_attributes)
        left_attributes.update(
            {
                "血气上限": 10000,
                "精神上限": 1000,
                "攻击": 20,
                "速度": 100,
                "暴击率": 60,
                "格挡率": 45,
                "闪避率": 20,
                "护盾上限": 100,
            }
        )
        right_attributes = dict(left_attributes)
        for seed, (group_id, enchantment_ids) in enumerate(
            self.content.enchantment_groups.items(),
            start=1,
        ):
            direction_id = self.content.enchantment_group_directions[group_id]
            technique_group = next(
                key
                for key, value in self.content.technique_group_directions.items()
                if value == direction_id
            )
            active_technique = next(
                technique_id
                for technique_id in self.content.technique_groups[technique_group]
                if self.content.technique_definitions[technique_id]["职责"] == "主动"
            )
            loadout = (
                self.technique(active_technique, 1),
                *(
                    self.content.configured_weapon_augment(
                        "附魔",
                        enchantment_id,
                        "黄品",
                        instance_id=f"{group_id}:{enchantment_id}",
                    )
                    for enchantment_id in enchantment_ids
                ),
            )
            outcome = self.engine.simulate(
                left=CombatantSnapshot(
                    id=f"left:{group_id}",
                    name="甲",
                    attributes=left_attributes,
                    health=10000,
                    spirit=1000,
                    techniques=loadout,
                ),
                right=CombatantSnapshot(
                    id=f"right:{group_id}",
                    name="乙",
                    attributes=right_attributes,
                    health=10000,
                    spirit=1000,
                    techniques=(self.technique(active_technique, 1),),
                ),
                item_definitions=self.content.combat_item_definitions(),
                seed=seed,
                action_limit=20,
            )
            self.assertTrue(outcome.events, group_id)

    def test_grade_scales_power_and_keeps_weight_separate(self) -> None:
        self.assertEqual(
            tuple(self.content.grade_definitions),
            ("黄品", "玄品", "地品", "天品", "圣品"),
        )
        self.assertEqual(
            self.content.choose_grade(FixedRandom(0.5, 0.5, 0.5, 0.5, 0.5)),
            "黄品",
        )
        self.assertTrue(self.content.grade_at_least("地品", "玄品"))
        self.assertFalse(self.content.grade_at_least("玄品", "地品"))
        self.assertTrue(self.content.grade_at_least("圣品", "天品"))
        self.assertFalse(self.content.grade_at_least("天品", "圣品"))

        item = self.content.graded_item_definition("草原灵植", "地品")
        self.assertEqual(item["名称"], "地品·草原灵植")
        self.assertEqual(item["参考价"], 55)
        self.assertEqual(item["品级"], "地品")

        gem_id = self.sample_gems[0]
        gem = self.content.configured_weapon_augment(
            "宝石",
            gem_id,
            "圣品",
            instance_id="gem:test",
        )
        self.assertEqual(gem["品级"], "圣品")
        self.assertEqual(gem["威力倍率"], 1.5)
        self.assertEqual(
            gem["评分"],
            int(self.content.gem_definitions[gem_id]["评分"] * 1.5 + 0.5),
        )
        gem_attributes = dict(self.player_attributes)
        fixed_node = next(
            value
            for value in self.content.gem_definitions[gem_id]["组成"]
            if value["能力"] == "固定属性加成"
        )
        attribute, base_value = next(iter(fixed_node["属性"].items()))
        before = gem_attributes.get(attribute, 0)
        self.engine._technique_rules([gem], gem_attributes)
        self.assertAlmostEqual(gem_attributes[attribute], before + base_value * 1.5)

        technique = self.technique(self.sample_active_techniques[0], 1)
        technique["威力倍率"] = 1.32
        fixed = next(
            node
            for node in technique["能力"]
            if node["能力"] == "固定属性加成"
        )
        attribute, amount = next(iter(fixed["属性"].items()))
        attributes = dict(self.player_attributes)
        before = attributes.get(attribute, 0)
        self.engine._technique_rules([technique], attributes)
        self.assertAlmostEqual(attributes[attribute], before + amount * 1.32)

        source = self.fighter("grade-source", health=100)
        target = self.fighter("grade-target", health=100)
        context = self.context(source, target)
        for index in range(3):
            self.engine._apply_status(
                context,
                target,
                source,
                {"状态": {"名称": f"负面{index}", "分类": "负面", "持续数值": 2}},
                1.0,
            )
        self.engine._execute_mechanism_reference(
            context,
            source,
            target,
            "澄心见月",
            1.32,
        )
        self.assertFalse(any(status.category == "负面" for status in source.statuses))
        self.engine._execute_mechanism_reference(
            context,
            source,
            target,
            "无垢莲台",
            1.32,
        )
        lotus = next(status for status in source.statuses if status.name == "无垢莲台")
        self.assertEqual(lotus.remaining_turns, 3)

        grades = deepcopy(self.content.grades)
        grades["品级"]["玄品"]["阶序"] = 1
        with self.assertRaisesRegex(GameContentError, "玄品.阶序：必须为 2"):
            _validate(replace(self.content, grades=grades))

    def test_graded_items_persist_scale_and_migrate_old_stacks(self) -> None:
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "game.db"
            services = build_game_services(
                data_dir=ROOT / "data",
                database_path=database_path,
            )
            services.player.ensure("grade-user", "品级测试")
            initial = services.player.load("grade-user")
            self.assertEqual(initial.inventory["黄品·小还丹"], 3)

            with services.database.transaction(write=True) as connection:
                player = services.player.load_player_in_connection(connection, "grade-user")
                player.health = 0
                services.player.update_player_in_connection(
                    connection,
                    player,
                    expected_revision=player.revision,
                )
                services.player.add_item_in_connection(
                    connection,
                    "grade-user",
                    "小还丹",
                    1,
                    "圣品",
                )

            page = services.player.inventory_page("grade-user", "丹药")
            entries = {entry.name: entry for entry in page.entries}
            self.assertEqual(entries["圣品·小还丹"].score, 45)
            self.assertEqual(entries["圣品·小还丹"].reference_price, 126)
            used = services.player.use_item("grade-user", "圣品·小还丹", 1)
            self.assertEqual((used.status, used.quantity, used.recovered), ("used", 1, 45))
            self.assertEqual(services.player.load("grade-user").player.health, 45)

            with services.database.transaction(write=True) as connection:
                connection.execute(
                    "ALTER TABLE inventory_stacks RENAME TO inventory_stacks_current"
                )
                connection.execute(
                    """
                    CREATE TABLE inventory_stacks (
                        user_id TEXT NOT NULL,
                        item_id TEXT NOT NULL,
                        quantity INTEGER NOT NULL CHECK (quantity >= 0),
                        PRIMARY KEY (user_id, item_id)
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO inventory_stacks(user_id, item_id, quantity)
                    SELECT user_id, item_id, SUM(quantity)
                    FROM inventory_stacks_current
                    GROUP BY user_id, item_id
                    """
                )
                connection.execute("DROP TABLE inventory_stacks_current")

            services.player.initialize()
            with services.database.transaction() as connection:
                columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(inventory_stacks)")
                }
            self.assertIn("grade_id", columns)
            migrated = services.player.load("grade-user")
            self.assertEqual(migrated.inventory["黄品·小还丹"], 3)

    def test_exploration_preserves_item_grades_and_uses_lowest_medicine_first(self) -> None:
        clock = MutableClock()
        with TemporaryDirectory() as directory:
            services = build_game_services(
                data_dir=ROOT / "data",
                database_path=Path(directory) / "game.db",
                clock=clock,
            )
            services.player.ensure("grade-explorer", "品级探险")
            self.assertEqual(
                services.location.move("grade-explorer", "朔风原").status,
                "moved",
            )
            with services.database.transaction(write=True) as connection:
                player = services.player.load_player_in_connection(
                    connection,
                    "grade-explorer",
                )
                player.health = 1
                player.attributes["速度"] = 1000
                player.attributes["攻击"] = 1000
                services.player.update_player_in_connection(
                    connection,
                    player,
                    expected_revision=player.revision,
                )
                services.player.add_item_in_connection(
                    connection,
                    "grade-explorer",
                    "小还丹",
                    1,
                    "圣品",
                )

            services.exploration.seed_factory = lambda: 1
            started = services.exploration.start("grade-explorer", "品级探险")
            self.assertEqual(started.status, "started")
            clock.advance(600)
            settlement = services.exploration.end("grade-explorer")
            self.assertIsNotNone(settlement)
            assert settlement is not None
            self.assertEqual(settlement.completed_rounds, 1)
            self.assertEqual(settlement.consumed_items, {"黄品·小还丹": 1})
            self.assertTrue(settlement.drops)
            self.assertTrue(all("·" in item_name for item_name in settlement.drops))

            assets = services.player.load("grade-explorer")
            self.assertEqual(assets.inventory["黄品·小还丹"], 2)
            self.assertEqual(assets.inventory["圣品·小还丹"], 1)
            for item_name, quantity in settlement.drops.items():
                self.assertEqual(assets.inventory[item_name], quantity)

    def test_partner_loadout_pools_live_in_world_and_are_validated(self) -> None:
        self.assertEqual(
            self.content.player["道侣"],
            {"功法位": 3, "附魔位": 3, "宝石位": 3, "好感上限": 100},
        )
        self.assertEqual(len(self.content.npc_definitions), 264)
        for pool_name in ("功法池", "附魔池", "宝石池"):
            self.assertEqual(
                len({definition[pool_name][0] for definition in self.content.npc_definitions.values()}),
                264,
            )
        for npc_id, definition in self.content.npc_definitions.items():
            self.assertEqual(definition["资质范围"], [1, 1000])
            self.assertTrue(definition["修行方向"])
            self.assertEqual(len(definition["功法池"]), 1)
            self.assertEqual(len(definition["附魔池"]), 1)
            self.assertEqual(len(definition["宝石池"]), 1)
            self.assertEqual(len(self.content.technique_groups[definition["功法池"][0]]), 9)
            self.assertEqual(len(self.content.enchantment_groups[definition["附魔池"][0]]), 9)
            self.assertEqual(len(self.content.gem_groups[definition["宝石池"][0]]), 9)
            candidates = self.content.npc_loadout_candidates(npc_id)
            self.assertEqual(len(candidates["功法"]), 9)
            self.assertEqual(len(candidates["附魔"]), 9)
            self.assertEqual(len(candidates["宝石"]), 9)
        self.assertTrue(
            all(definition["等级"] == 1 for definition in self.content.npc_definitions.values())
        )
        npc_id = self.content.npc_groups["青溪村道侣"][0]
        assigned_directions = [
            str(definition["修行方向"])
            for definition in self.content.npc_definitions.values()
        ]
        self.assertEqual(len(set(assigned_directions)), 264)
        self.assertTrue(
            {"本命武器", "功法", "战斗策略", "纳戒", "掉落"}.isdisjoint(
                self.content.npc_definitions[npc_id]
            )
        )
        group_id = self.content.npc_definitions[npc_id]["功法池"][0]
        direction_id = self.content.technique_group_directions[group_id]
        techniques = deepcopy(self.content.techniques)
        techniques["分组"][group_id] = techniques["分组"][group_id][:8]
        with self.assertRaisesRegex(
            GameContentError,
            f"战斗方向.{direction_id}的功法池至少需要9项",
        ):
            _validate(replace(self.content, techniques=techniques))

        npcs = deepcopy(self.content.npcs)
        npcs["道侣"][npc_id]["功法池"] = ["不存在的功法池"]
        with self.assertRaisesRegex(GameContentError, f"{npc_id}.功法池：引用不存在"):
            _validate(replace(self.content, npcs=npcs))

        npcs = deepcopy(self.content.npcs)
        second_npc_id = next(value for value in npcs["道侣"] if value != npc_id)
        npcs["道侣"][second_npc_id]["修行方向"] = npcs["道侣"][npc_id]["修行方向"]
        for field in ("功法池", "附魔池", "宝石池"):
            npcs["道侣"][second_npc_id][field] = list(
                npcs["道侣"][npc_id][field]
            )
        with self.assertRaisesRegex(GameContentError, "修行方向.*已属于道侣"):
            _validate(replace(self.content, npcs=npcs))

        npcs = deepcopy(self.content.npcs)
        npcs["道侣"][npc_id]["宝石池"].append(
            self.content.npc_definitions[second_npc_id]["宝石池"][0]
        )
        with self.assertRaisesRegex(GameContentError, "宝石池：必须且只能引用一个 JSON"):
            _validate(replace(self.content, npcs=npcs))

        npcs = deepcopy(self.content.npcs)
        npcs["道侣"][npc_id]["纳戒"] = {"灵石": 0, "物品": []}
        with self.assertRaisesRegex(GameContentError, f"{npc_id}.*纳戒"):
            _validate(replace(self.content, npcs=npcs))

    def test_json_alias_and_new_technique_need_no_python_branch(self) -> None:
        alias = deepcopy(self.content.atomic_ability_definitions["造成伤害"])
        mechanism = {
            "能力": "灵焰冲击",
            "名称": "试制灵焰",
            "目标": {"能力": "选择目标", "范围": "当前目标"},
            "数值": {
                "能力": "读取数值",
                "来源": "自身属性",
                "属性": "攻击",
                "百分比": 100,
            },
            "能否暴击": False,
            "能否格挡": False,
        }
        technique_definition = deepcopy(
            self.content.technique_definitions[self.sample_active_techniques[0]]
        )
        technique_definition.update(
            {
                "说明": "只由已登记规则组合出的测试功法。",
                "权重": 40,
                "评分": 100,
                "组成": [
                    {"能力": "固定属性加成", "属性": {"攻击": 3}},
                    {
                        "能力": "主动技能",
                        "名称": "灵焰式",
                        "释放顺序": 990001,
                        "精神消耗": 0,
                        "冷却回合": 0,
                        "效果": [
                            {"能力": "引用战斗机制", "机制": "试制灵焰"}
                        ],
                    },
                ],
            }
        )
        with TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            shutil.copytree(ROOT / "data" / "rules", data_dir / "rules")
            shutil.copytree(ROOT / "data" / "content", data_dir / "content")
            changes = (
                (data_dir / "rules" / "战斗" / "原子能力.json", "原子能力", "灵焰冲击", alias),
                (data_dir / "content" / "战斗机制" / "机制.json", "机制", "试制灵焰", mechanism),
            )
            for path, section, key, value in changes:
                data = json.loads(path.read_text(encoding="utf-8"))
                data[section][key] = value
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            technique_path = (
                data_dir
                / "content"
                / "物品"
                / "功法"
                / f"{self.sample_technique_group}.json"
            )
            technique_catalog = json.loads(technique_path.read_text(encoding="utf-8"))
            technique_catalog["功法"]["试制功法"] = technique_definition
            technique_path.write_text(
                json.dumps(technique_catalog, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            configured = GameContent.load(JsonDataReader(data_dir))

        engine = BattleEngine(configured.combat)
        instance = {
            "实例": "json-only",
            "功法": "试制功法",
            "出生序号": 1,
            "威力倍率": 1.0,
            "词条": [],
            "能力": configured.technique_definitions["试制功法"]["组成"],
        }
        outcome = engine.simulate(
            left=CombatantSnapshot(
                id="player",
                name="测试修士",
                attributes=self.player_attributes,
                health=100,
                spirit=60,
                weapon_attack=10,
                techniques=(instance,),
            ),
            right=self.enemy_snapshot("石门守修", 11, content=configured),
            item_definitions=configured.combat_item_definitions(),
            seed=11,
            action_limit=1,
        )
        damage = next(event for event in outcome.events if event.mechanism == "试制灵焰")
        self.assertEqual(damage.kind, "damage")
        self.assertTrue(damage.text.startswith("试制灵焰"))

    def test_lifesteal_reflection_counter_and_combo(self) -> None:
        player = self.fighter("player", health=50, **{"吸血率": 100, "攻击": 20})
        shielded = self.fighter("shielded", shield=20)
        context = self.context(player, shielded)
        self.engine._deal_attack(
            context,
            player,
            shielded,
            1,
            "护盾验算",
            can_miss=False,
            can_critical=False,
            can_block=False,
        )
        self.assertEqual(player.health, 50, "吸血不能读取护盾伤害")
        self.assertEqual(shielded.health, 100)

        attacker = self.fighter("player", **{"攻击": 20})
        defender = self.fighter(
            "enemy",
            **{"攻击": 20, "反伤率": 100, "反击率": 100},
        )
        context = self.context(attacker, defender)
        self.engine._deal_attack(
            context,
            attacker,
            defender,
            0.5,
            "反应验算",
            can_miss=False,
            can_critical=False,
            can_block=False,
        )
        self.assertEqual(defender.health, 90)
        self.assertEqual(attacker.health, 70)
        self.assertTrue(any(event.text.startswith("反伤") for event in context.events))
        self.assertTrue(any(event.text.startswith("反击") for event in context.events))

        attacker = self.fighter(
            "player",
            **{"攻击": 20, "连击率": 100, "连击伤害": 50},
        )
        defender = self.fighter("enemy")
        context = self.context(attacker, defender)
        self.engine._deal_attack(
            context,
            attacker,
            defender,
            1,
            "连击验算",
            can_miss=False,
            can_critical=False,
            can_block=False,
        )
        self.assertEqual(defender.health, 70)
        combo = next(
            event
            for event in context.events
            if event.kind == "damage" and "派生伤害" in event.tags
        )
        self.assertIn("派生伤害", combo.tags)

    def test_derived_damage_does_not_repeat_listener(self) -> None:
        combat = deepcopy(self.content.combat)
        combat["机制"]["原始回气"] = {
            "能力": "监听事件",
            "事件": "造成伤害后",
            "事件关系": "自身为来源",
            "每次行动最多触发": 5,
            "效果": [
                {
                    "能力": "恢复资源",
                    "目标": {"能力": "选择目标", "范围": "自身"},
                    "资源": "精神",
                    "数值": {"能力": "读取数值", "来源": "固定值", "固定值": 1},
                }
            ],
        }
        engine = BattleEngine(combat)
        attributes = dict(self.player_attributes)
        attributes.update({"连击率": 100, "连击伤害": 50, "速度": 500})
        enemy = deepcopy(self.content.enemy_definitions["山道劫修"])
        enemy["属性"].update({"血气上限": 1000, "速度": 1})
        technique = {
            "实例": "listener",
            "功法": "监听验算",
            "出生序号": 1,
            "威力倍率": 1.0,
            "词条": [],
            "能力": [
                {
                    "能力": "被动技能",
                    "名称": "监听验算",
                    "结算顺序": 990001,
                    "效果": [{"能力": "引用被动机制", "机制": "原始回气"}],
                }
            ],
        }
        outcome = engine.simulate(
            left=CombatantSnapshot(
                id="player",
                name="测试修士",
                attributes=attributes,
                health=100,
                spirit=0,
                weapon_attack=10,
                techniques=(technique,),
            ),
            right=self.enemy_snapshot("山道劫修", 9, definition=enemy),
            item_definitions=self.content.combat_item_definitions(),
            seed=9,
            action_limit=1,
        )
        self.assertEqual(outcome.left.spirit, 1)
        self.assertEqual(outcome.trigger_activations, 1)

    def test_fatal_guard_activates_once(self) -> None:
        player = self.fighter("player", health=20)
        enemy = self.fighter("enemy", **{"攻击": 100})
        passive = ({"机制": "一息还真", "实例": "guard", "威力倍率": 1.0},)
        context = self.context(player, enemy, passives=passive)

        self.engine._apply_damage(
            context,
            enemy,
            player,
            100,
            can_critical=False,
            can_block=False,
        )
        self.assertEqual(player.health, 16)
        self.engine._apply_damage(
            context,
            enemy,
            player,
            100,
            can_critical=False,
            can_block=False,
        )
        self.assertEqual(player.health, 0)
        self.assertEqual(sum(event.kind == "fatal_guard" for event in context.events), 1)
        self.assertEqual(sum(event.kind == "受到致命伤害" for event in context.events), 2)
        first_damage = next(index for index, event in enumerate(context.events) if event.kind == "damage")
        first_recovery = next(index for index, event in enumerate(context.events) if event.kind == "recover")
        self.assertLess(first_damage, first_recovery)

    def test_equipped_techniques_follow_release_order_and_multi_hit_is_atomic(self) -> None:
        expected_efficiency = {25: 0.4, 70: 14 / 17, 100: 1.0, 200: 4 / 3, 500: 5 / 3}
        for speed, expected in expected_efficiency.items():
            self.assertAlmostEqual(self.engine._action_efficiency(speed), expected)

        names = list(self.sample_active_techniques[:3])
        outcome = self.simulate(names)
        skill_events = [
            event
            for event in outcome.events
            if event.kind == "skill" and event.source_id == "player"
        ]
        used = {event.values.get("技能") for event in skill_events}
        self.assertTrue(set(names).issubset(used))
        expected_first = min(
            names,
            key=lambda name: next(
                node["释放顺序"]
                for node in self.content.technique_definitions[name]["组成"]
                if node["能力"] == "主动技能"
            ),
        )
        self.assertEqual(skill_events[0].values.get("技能"), expected_first)

        multi_hit = self.active_technique("踏罡三叩验算", "踏罡三叩")
        outcome = self.engine.simulate(
            left=CombatantSnapshot(
                id="multi-hit",
                name="甲",
                attributes=self.player_attributes,
                health=100,
                spirit=60,
                techniques=(multi_hit,),
            ),
            right=self.enemy_snapshot("石门守修", 17),
            item_definitions=self.content.combat_item_definitions(),
            seed=17,
            action_limit=1,
        )
        hits = [
            event
            for event in outcome.events
            if event.kind == "damage" and event.mechanism == "踏罡三叩"
        ]
        self.assertGreaterEqual(len(hits), 3)
        self.assertTrue(
            all(
                event.text.startswith(name)
                for event, name in zip(hits[:3], ("踏罡一叩", "踏罡二叩", "踏罡三叩"))
            )
        )

    def test_periodic_damage_probability_source_and_display(self) -> None:
        fire_technique = self.active_technique("离火验算", "离火灼身")
        fire = self.engine.simulate(
            left=CombatantSnapshot(
                id="fire-source",
                name="甲",
                attributes=self.player_attributes,
                health=100,
                spirit=60,
                techniques=(fire_technique,),
            ),
            right=self.enemy_snapshot("石门守修", 18),
            item_definitions=self.content.combat_item_definitions(),
            seed=18,
            action_limit=2,
        )
        self.assertTrue(
            any(
                event.text.startswith("离火灼身") and event.mechanism == "离火灼身"
                for event in fire.events
            )
        )
        self.assertFalse(any(event.kind == "状态造成伤害" for event in fire.events))

        enemy_fire = {
            **fire_technique,
            "实例": "enemy-fire",
        }
        fast_enemy = dict(self.player_attributes)
        fast_enemy.update({"速度": 500, "血气上限": 1000})
        slow_player = dict(self.player_attributes)
        slow_player.update({"速度": 1, "血气上限": 1000})
        applied = self.engine.simulate(
            left=CombatantSnapshot(
                id="player",
                name="测试修士",
                attributes=slow_player,
                health=1000,
                spirit=60,
            ),
            right=CombatantSnapshot(
                id="opponent:3",
                name="密林火修",
                attributes=fast_enemy,
                health=1000,
                spirit=60,
                techniques=(enemy_fire,),
            ),
            item_definitions=self.content.combat_item_definitions(),
            seed=3,
            action_limit=1,
        )
        self.assertTrue(any(status.name == "离火灼身" for status in applied.left.statuses))

        continued = self.simulate(
            seed=4,
            action_limit=1,
            enemy_id="石门守修",
            statuses=[status.to_dict() for status in applied.left.statuses],
        )
        old_source_events = [
            event
            for event in continued.events
            if event.kind == "damage" and event.source_id == "opponent:3"
        ]
        self.assertTrue(old_source_events)
        self.assertTrue(all(event.source == "密林火修" for event in old_source_events))

        text = _mechanism_text(
            dict(self.content.mechanism_definitions["离火灼身"]),
            1.0,
            self.content.attribute_definitions,
        )
        self.assertNotIn("时施加", text)
        self.assertNotIn("造成伤害造成", text)

    def test_extended_reference_mechanisms_execute_and_render(self) -> None:
        expected = {
            "赤狱蚀脉",
            "焚心劫灰",
            "纳劫入炉",
            "开炉还劫",
            "碎璧飞光",
            "叠璧成城",
            "澄心见月",
            "无垢莲台",
            "听潮夺元",
            "焚元一掷",
            "破障归虚",
            "鲸息纳元",
            "枯荣倒悬",
            "惊鸿借隙",
            "镇岳迟轮",
            "断念封窍",
            "六爻错机",
            "断命一线",
            "照骨印",
            "引雷契",
            "青莲九转",
            "催莲成华",
            "三问归一",
            "两仪换势",
            "逆潮锁轮",
            "玄壳回潮",
            "返魂灯",
            "赤练焚络",
        }
        self.assertTrue(expected.issubset(self.content.mechanism_definitions))

        for mechanism_id, definition in self.content.mechanism_definitions.items():
            with self.subTest(mechanism=mechanism_id):
                text = _mechanism_text(
                    dict(definition),
                    1.0,
                    self.content.attribute_definitions,
                    ability_definitions=self.content.atomic_ability_definitions,
                    mechanism_definitions=self.content.mechanism_definitions,
                )
                self.assertTrue(text.strip())
                if self.content.ability_executor(dict(definition)) == "监听事件":
                    continue
                source = self.fighter("source", health=80, shield=40, **{"攻击": 20})
                source.spirit = 60
                target = self.fighter("target", health=100, shield=20)
                target.spirit = 40
                context = self.context(source, target)
                self.engine._execute_mechanism_reference(
                    context,
                    source,
                    target,
                    mechanism_id,
                    1.0,
                )

    def test_new_status_resource_action_and_revival_paths(self) -> None:
        source = self.fighter("source", health=100, shield=20, **{"攻击": 20})
        source.spirit = 10
        target = self.fighter("target", health=100, **{"攻击": 30})
        target.spirit = 50
        context = self.context(source, target)

        self.engine._execute_mechanism_reference(context, source, target, "听潮夺元", 1.0)
        self.assertGreater(source.spirit, 10)
        self.assertLess(target.spirit, 50)

        self.engine._execute_mechanism_reference(context, source, target, "赤狱蚀脉", 1.0)
        self.engine._execute_mechanism_reference(context, source, target, "赤狱蚀脉", 1.0)
        burning = next(status for status in target.statuses if status.name == "赤狱蚀脉")
        self.assertEqual(burning.stacks, 2)

        self.engine._execute_mechanism_reference(context, source, target, "无垢莲台", 1.0)
        before = len(source.statuses)
        self.engine._execute_mechanism_reference(context, target, source, "镇岳迟轮", 1.0)
        self.assertEqual(len(source.statuses), before, "状态免疫必须阻止负面状态")

        guarded = self.fighter("guarded", health=100, shield=20)
        guarded.spirit = 0
        attacker = self.fighter("attacker", **{"攻击": 100})
        passives = tuple(
            {"机制": name, "实例": f"passive:{name}", "威力倍率": 1.0}
            for name in ("纳劫入炉", "玄壳回潮", "返魂灯")
        )
        battle = self.context(guarded, attacker, passives=passives)
        self.engine._apply_damage(
            battle,
            attacker,
            guarded,
            30,
            can_critical=False,
            can_block=False,
        )
        self.assertTrue(any(status.name == "劫火" for status in guarded.statuses))
        self.assertGreater(guarded.spirit, 0)
        self.assertGreater(battle.action_progress[guarded.id], 0)

        self.engine._apply_damage(
            battle,
            attacker,
            guarded,
            500,
            can_critical=False,
            can_block=False,
        )
        self.assertTrue(guarded.alive)
        self.assertEqual(guarded.health, 25)
        self.assertEqual(sum(event.kind == "revive" for event in battle.events), 1)

    def test_extended_mechanism_boundaries_stay_bounded(self) -> None:
        source = self.fighter("source", health=100, shield=10)
        target = self.fighter("target", health=100, shield=10)

        fractional_context = self.context(source, target)
        rolled = self.engine._value_random(
            fractional_context,
            {"最低值": 1.2, "最高值": 1.8, "取整": True},
            source,
            target,
            0,
            {},
        )
        self.assertIn(rolled, {1.0, 2.0})

        shield_passive = (
            {"机制": "玄壳回潮", "实例": "passive:shield", "威力倍率": 1.0},
        )
        for executor in ("消耗资源", "设置资源"):
            with self.subTest(executor=executor):
                shielded = self.fighter(f"shielded:{executor}", health=100, shield=10)
                opponent = self.fighter(f"opponent:{executor}")
                context = self.context(shielded, opponent, passives=shield_passive)
                self.engine._execute_mechanism(
                    context,
                    opponent,
                    shielded,
                    {
                        "能力": executor,
                        "目标": {"能力": "选择目标", "范围": "当前目标"},
                        "资源": "护盾",
                        "数值": 10 if executor == "消耗资源" else 0,
                    },
                    1.0,
                    event_amount=0,
                    event_values={},
                )
                self.assertEqual(shielded.shield, 0)
                self.assertGreater(context.action_progress[shielded.id], 0)
                self.assertEqual(
                    sum(event.kind == "action_progress" for event in context.events),
                    1,
                )

        revived = self.fighter("revived", health=100)
        revived.health = 0
        opponent = self.fighter("reviver")
        revive_context = self.context(revived, opponent)
        self.engine._mechanism_revive(
            revive_context,
            revived,
            opponent,
            {
                "目标": {"能力": "选择目标", "范围": "自身"},
                "血气百分比": 25,
            },
            10.0,
        )
        self.assertEqual(revived.health, revived.health_max)

    def test_mechanism_counter_obeys_bounds_and_insufficient_cost(self) -> None:
        source = self.fighter("counter-source")
        target = self.fighter("counter-target")
        context = self.context(source, target)

        def modify(mode: str, amount: float) -> None:
            self.engine._mechanism_modify_counter(
                context,
                source,
                target,
                {
                    "能力": "修改机制计量",
                    "目标": {"能力": "选择自身", "范围": "自身"},
                    "计量": "剑意",
                    "方式": mode,
                    "数值": amount,
                    "最低值": 0,
                    "最高值": 100,
                    "不足时是否失败": True,
                },
                1.0,
            )

        modify("增加", 150)
        self.assertEqual(context.mechanism_counters[(source.id, "剑意")], 100)
        modify("减少", 120)
        self.assertEqual(context.mechanism_counters[(source.id, "剑意")], 100)
        modify("减少", 30)
        value = self.engine._value_read(
            context,
            {
                "能力": "读取数值",
                "来源": "机制计量",
                "目标": {"能力": "选择自身", "范围": "自身"},
                "计量": "剑意",
            },
            source,
            target,
            0,
            {},
        )
        self.assertEqual(value, 70)

    def test_charge_progress_survives_consecutive_encounters(self) -> None:
        technique = {
            "实例": "charge-technique",
            "功法": "引雷诀",
            "品级": "黄品",
            "出生序号": 1,
            "威力倍率": 1.0,
            "词条": [],
            "能力": [
                {
                    "能力": "主动技能",
                    "名称": "引雷落霄",
                    "释放顺序": 1,
                    "精神消耗": 5,
                    "冷却回合": 0,
                    "蓄势回合": 2,
                    "效果": [
                        {
                            "能力": "造成伤害",
                            "名称": "引雷落霄",
                            "目标": {"能力": "选择目标", "范围": "当前目标"},
                            "数值": 30,
                            "伤害形式": "直接",
                            "防御规则": "真实",
                            "能否暴击": False,
                            "能否格挡": False,
                        }
                    ],
                }
            ],
        }
        attributes = dict(self.player_attributes)
        attributes.update({"速度": 200, "命中率": 100})
        enemy_attributes = dict(self.player_attributes)
        enemy_attributes.update({"血气上限": 500, "速度": 1, "闪避率": 0})
        left = CombatantSnapshot(
            id="charger",
            name="蓄势修士",
            attributes=attributes,
            health=100,
            spirit=60,
            techniques=(technique,),
        )

        for expected_progress in (1, 2):
            outcome = self.engine.simulate(
                left=left,
                right=CombatantSnapshot(
                    id=f"dummy:{expected_progress}",
                    name="木桩",
                    attributes=enemy_attributes,
                    health=500,
                    spirit=0,
                ),
                item_definitions={},
                seed=expected_progress,
                action_limit=1,
            )
            self.assertEqual(tuple(outcome.left.charge_progress.values()), (expected_progress,))
            self.assertTrue(outcome.left.charging_skill)
            self.assertFalse(any(event.kind == "damage" for event in outcome.events))
            left = replace(
                left,
                health=outcome.left.health,
                spirit=outcome.left.spirit,
                charge_progress=outcome.left.charge_progress,
                charging_skill=outcome.left.charging_skill,
            )

        released = self.engine.simulate(
            left=left,
            right=CombatantSnapshot(
                id="dummy:released",
                name="木桩",
                attributes=enemy_attributes,
                health=500,
                spirit=0,
            ),
            item_definitions={},
            seed=3,
            action_limit=1,
        )
        self.assertFalse(released.left.charge_progress)
        self.assertEqual(released.left.charging_skill, "")
        self.assertTrue(any(event.kind == "damage" for event in released.events))

    def test_additional_actions_have_a_hard_recursive_limit(self) -> None:
        source = self.fighter("pursuer", **{"攻击": 10, "命中率": 100})
        target = self.fighter("target", health=100, **{"闪避率": 0})
        node = {
            "能力": "监听事件",
            "事件": "普通攻击后",
            "事件关系": "自身为来源",
            "接受派生事件": True,
            "效果": [
                {
                    "能力": "追加行动",
                    "名称": "连环追击",
                    "目标": {"能力": "选择目标", "范围": "当前目标"},
                    "行动类型": "普通攻击",
                    "威力倍率": 100,
                    "每次主行动最多追加": 3,
                }
            ],
        }
        source.passives = tuple(
            {
                "机制": f"追击链{index}",
                "节点": dict(node),
                "实例": f"追击链:{index}",
                "结算顺序": index,
                "威力倍率": 1.0,
            }
            for index in range(1, 5)
        )
        context = self.context(source, target, passives=source.passives)
        self.engine._basic_attack(context, source, target)
        self.assertEqual(
            sum(event.kind == "追加行动后" for event in context.events),
            3,
        )
        self.assertEqual(sum(event.kind == "damage" for event in context.events), 4)
        self.assertEqual(target.health, 60)

    def test_damage_share_and_transfer_resolve_before_original_damage(self) -> None:
        target = self.fighter("ward", health=200)
        guardian = self.fighter("guardian", health=200)
        redirector = self.fighter("redirector", health=200)
        attacker = self.fighter("attacker", health=200, **{"攻击": 100})
        guardian.passives = (
            {
                "机制": "同阵分伤",
                "节点": {
                    "能力": "监听事件",
                    "事件": "造成伤害前",
                    "事件关系": "自身与承受者同阵营",
                    "效果": [
                        {
                            "能力": "分摊伤害",
                            "名称": "同阵分伤",
                            "目标": {"能力": "选择自身", "范围": "自身"},
                            "比例": 50,
                        }
                    ],
                },
                "实例": "guardian-share",
                "结算顺序": 1,
                "威力倍率": 1.0,
            },
        )
        redirector.passives = (
            {
                "机制": "移祸承伤",
                "节点": {
                    "能力": "监听事件",
                    "事件": "造成伤害前",
                    "事件关系": "自身与承受者同阵营",
                    "效果": [
                        {
                            "能力": "转移伤害",
                            "名称": "移祸承伤",
                            "目标": {"能力": "选择自身", "范围": "自身"},
                            "数值": 10,
                        }
                    ],
                },
                "实例": "redirector-transfer",
                "结算顺序": 2,
                "威力倍率": 1.0,
            },
        )
        context = BattleContext(
            rng=random.Random(7),
            left=target,
            right=attacker,
            item_definitions={},
            left_team=(target, guardian, redirector),
            right_team=(attacker,),
        )
        context.engine = self.engine
        context.action_progress = {fighter.id: 0.0 for fighter in context.fighters}
        self.engine._apply_damage(
            context,
            attacker,
            target,
            100,
            defense_rule="真实",
            can_critical=False,
            can_block=False,
        )
        self.assertEqual(target.health, 160)
        self.assertEqual(guardian.health, 150)
        self.assertEqual(redirector.health, 190)
        original = next(
            event for event in context.events
            if event.kind == "damage" and event.target_id == target.id
        )
        self.assertEqual(original.values["已分摊伤害"], 50)
        self.assertEqual(original.values["已转移伤害"], 10)

    def test_same_technique_executes_identically_on_both_sides(self) -> None:
        technique = self.technique(self.sample_active_techniques[0], 1)
        fighter_attributes = dict(self.player_attributes)
        fighter_attributes["速度"] = 100
        dummy_attributes = dict(self.player_attributes)
        dummy_attributes.update({"血气上限": 1000, "速度": 1})

        def snapshot(fighter_id: str, *, fighter: bool) -> CombatantSnapshot:
            return CombatantSnapshot(
                id=fighter_id,
                name=fighter_id,
                attributes=fighter_attributes if fighter else dummy_attributes,
                health=100 if fighter else 1000,
                spirit=60,
                weapon_attack=10 if fighter else 0,
                techniques=(technique,) if fighter else (),
            )

        left_run = self.engine.simulate(
            left=snapshot("left-cultivator", fighter=True),
            right=snapshot("right-dummy", fighter=False),
            item_definitions=self.content.combat_item_definitions(),
            seed=77,
            action_limit=1,
        )
        right_run = self.engine.simulate(
            left=snapshot("left-dummy", fighter=False),
            right=snapshot("right-cultivator", fighter=True),
            item_definitions=self.content.combat_item_definitions(),
            seed=77,
            action_limit=1,
        )
        left_events = [
            (event.kind, event.mechanism, event.amount)
            for event in left_run.events
            if event.kind in {"skill", "damage", "recover", "status"}
        ]
        right_events = [
            (event.kind, event.mechanism, event.amount)
            for event in right_run.events
            if event.kind in {"skill", "damage", "recover", "status"}
        ]
        self.assertEqual(left_events, right_events)

    def test_enemy_cultivator_uses_own_medicine_and_only_drops_inventory(self) -> None:
        enemy_definition = self.content.enemy_definitions["山道劫修"]
        self.assertEqual(enemy_definition["类别"], "修士")
        self.assertNotIn("功法", enemy_definition)
        self.assertNotIn("本命武器", enemy_definition["掉落"])
        enemy_instance = self.enemies.spawn("山道劫修", seed=23)
        self.assertIn(enemy_instance.level, range(1, 4))
        self.assertGreater(enemy_instance.weapon_attack, 0)
        self.assertIn(enemy_instance.direction_id, self.content.direction_definitions)
        self.assertEqual(
            (
                len(enemy_instance.technique_ids),
                len(enemy_instance.enchantment_ids),
                len(enemy_instance.gem_ids),
            ),
            (6, 6, 6),
        )
        self.assertFalse(self._enemy_loadout_issues(enemy_instance))
        self.assertNotIn(enemy_definition["本命武器"]["名称"], enemy_instance.inventory)
        self.assertTrue(
            all("·" in item_name for item_name in enemy_instance.inventory)
        )
        self.assertEqual(sum(enemy_instance.inventory.values()), 1)

        beast = self.enemies.spawn("青牙山犬", seed=23)
        self.assertEqual(beast.kind, "灵兽")
        self.assertEqual(beast.weapon_attack, 0)
        self.assertFalse(beast.inventory)
        self.assertFalse(beast.fixed_drops)
        left_attributes = dict(self.player_attributes)
        left_attributes.update({"攻击": 20, "速度": 200})
        outcome = self.engine.simulate(
            left=CombatantSnapshot(
                id="player",
                name="玩家",
                attributes=left_attributes,
                health=100,
                spirit=60,
            ),
            right=replace(
                enemy_instance.battle_snapshot(),
                inventory={"圣品·小还丹": 1, "地品·修为玉简": 1},
                auto_medicine=True,
                medicine_threshold=1.0,
            ),
            item_definitions=self.content.combat_item_definitions(),
            seed=23,
            action_limit=2,
        )
        self.assertEqual(outcome.right.consumed_items, {"圣品·小还丹": 1})
        self.assertEqual(outcome.right.inventory, {"地品·修为玉简": 1})

        boss = self.enemies.spawn("山道劫修", seed=24, rank="首领")
        self.assertEqual(boss.rank, "首领")
        self.assertIsNone(boss.direction_id)
        self.assertEqual(
            (len(boss.technique_ids), len(boss.enchantment_ids), len(boss.gem_ids)),
            (6, 6, 6),
        )
        self.assertFalse(self._enemy_loadout_issues(boss))

        with TemporaryDirectory() as directory:
            services = build_game_services(
                data_dir=ROOT / "data",
                database_path=Path(directory) / "game.db",
            )
            services.player.ensure("npc-loot-test", "测试修士")
            initial_assets = services.player.load("npc-loot-test")
            original_weapon = initial_assets.weapon.name
            original_medicine = initial_assets.inventory.get("黄品·小还丹", 0)
            nearby = services.npc.nearby("npc-loot-test")
            npc_id = services.content.npc_groups["青溪村道侣"][0]
            self.assertIn(npc_id, [value.npc_id for value in nearby])
            self.assertTrue(nearby[0].level_text.startswith("Lv"))
            spoken = services.npc.talk("npc-loot-test", npc_id, seed=1)
            self.assertIsNotNone(spoken)

            services.location.move("npc-loot-test", "朔风原")
            self.assertEqual(services.npc.nearby("npc-loot-test"), ())
            self.assertIsNone(
                services.npc.talk("npc-loot-test", npc_id, seed=1)
            )
            with services.database.transaction(write=True) as connection:
                services.exploration._apply_rewards(
                    connection,
                    "npc-loot-test",
                    [
                        {
                            "result": "victory",
                            "consumed_items": {},
                            "enemy_spirit_stones": 9,
                            "weapon_experience": 5,
                            "enemy_drops": dict(outcome.right.inventory),
                        }
                    ],
                )
            assets = services.player.load("npc-loot-test")
            self.assertEqual(assets.inventory.get("地品·修为玉简"), 1)
            self.assertEqual(
                assets.inventory.get("黄品·小还丹", 0),
                original_medicine,
            )
            self.assertEqual(assets.weapon.name, original_weapon)

    def _enemy_loadout_issues(self, enemy) -> tuple[str, ...]:
        return compatibility_issues(
            {
                "功法": tuple(
                    (value, self.content.technique_definitions[value])
                    for value in enemy.technique_ids
                ),
                "附魔": tuple(
                    (value, self.content.enchantment_definitions[value])
                    for value in enemy.enchantment_ids
                ),
                "宝石": tuple(
                    (value, self.content.gem_definitions[value])
                    for value in enemy.gem_ids
                ),
            },
            active_minimum=3,
            passive_minimum=3,
        )

    def test_cooldown_clear_and_selector_are_exact(self) -> None:
        player = self.fighter("player")
        enemy = self.fighter("enemy")
        context = self.context(player, enemy)
        player.cooldowns = {"a": 3, "b": 1}
        self.engine._mechanism_modify_cooldown(
            context,
            player,
            player,
            {
                "能力": "修改技能冷却",
                "目标": {"能力": "选择自身", "范围": "自身"},
                "技能": {
                    "能力": "选择技能",
                    "范围": "冷却中的技能",
                    "排序": "无",
                    "数量": 1,
                    "选择全部": True,
                },
                "方式": "清空",
                "数值": 0,
            },
            1.0,
        )
        self.assertEqual(player.cooldowns, {"a": 0, "b": 0})

    def test_partner_loadout_persists_and_joins_exploration_and_seclusion(self) -> None:
        clock = MutableClock()
        with TemporaryDirectory() as directory:
            services = build_game_services(
                data_dir=ROOT / "data",
                database_path=Path(directory) / "game.db",
                clock=clock,
            )
            user_id = "partner-loop"
            npc_id = services.content.npc_groups["青溪村道侣"][0]
            favorite_groups = services.content.npc_definitions[npc_id]["结交"][
                "喜爱天材地宝池"
            ]
            favorite_items = services.content.items_in_groups(list(favorite_groups))
            favorite = favorite_items[0]
            disliked = next(
                item_id
                for item_id, definition in services.content.item_definitions.items()
                if definition["类别"] == "天材地宝"
                and item_id not in favorite_items
            )
            services.player.ensure(user_id, "同行测试")
            with services.database.transaction(write=True) as connection:
                services.player.add_item_in_connection(
                    connection,
                    user_id,
                    favorite,
                    4,
                    services.player.lowest_grade_id,
                )
                services.player.add_item_in_connection(
                    connection,
                    user_id,
                    favorite_items[1],
                    1,
                    services.player.lowest_grade_id,
                )
                services.player.add_item_in_connection(
                    connection,
                    user_id,
                    disliked,
                    1,
                    services.player.lowest_grade_id,
                )
                services.player.add_item_in_connection(
                    connection,
                    user_id,
                    "同修玉简",
                    1,
                    services.player.lowest_grade_id,
                )
            rejected = services.npc.gift(user_id, npc_id, disliked)
            self.assertEqual(rejected.status, "not_preferred")
            self.assertEqual(
                services.player.load(user_id).inventory[
                    services.player.item_name(disliked, services.player.lowest_grade_id)
                ],
                1,
            )
            accepted_same_pool = services.npc.gift(
                user_id,
                npc_id,
                favorite_items[1],
            )
            self.assertEqual(accepted_same_pool.status, "gifted")
            gift = services.npc.gift(user_id, npc_id, favorite, 4)
            self.assertEqual(gift.status, "gifted")
            self.assertIsNotNone(gift.profile)
            assert gift.profile is not None
            self.assertEqual(gift.profile.favor, gift.profile.favor_max)

            services.npc.seed_factory = lambda: 123
            invited = services.npc.invite(user_id, npc_id)
            self.assertEqual(invited.status, "invited")
            self.assertIsNotNone(invited.partner)
            assert invited.partner is not None
            partner = invited.partner
            self.assertEqual(
                (len(partner.techniques), len(partner.enchantments), len(partner.gems)),
                (3, 3, 3),
            )
            self.assertEqual(len({value["功法"] for value in partner.techniques}), 3)
            self.assertEqual(len({value["名称"] for value in partner.enchantments}), 3)
            self.assertEqual(len({value["名称"] for value in partner.gems}), 3)
            self.assertEqual(
                services.npc.use_experience_item(
                    user_id,
                    "不存在的道侣",
                    "同修玉简",
                ).status,
                "target_not_found",
            )
            self.assertEqual(
                services.player.load(user_id).inventory["黄品·同修玉简"],
                1,
            )
            used = services.npc.use_experience_item(user_id, npc_id, "同修玉简")
            self.assertEqual(used.status, "used")
            self.assertEqual((used.experience, used.levels_gained), (100, 1))
            trained = services.npc.partner(user_id, npc_id)
            self.assertIsNotNone(trained)
            assert trained is not None
            self.assertEqual((trained.level, trained.experience), (2, 36))
            self.assertNotIn(
                "黄品·同修玉简",
                services.player.load(user_id).inventory,
            )
            battle_snapshot = services.npc.battle_snapshot(
                partner,
                inventory={},
                auto_medicine=True,
                medicine_threshold=0.3,
            )
            self.assertEqual(len(battle_snapshot.techniques), 9)
            self.assertEqual(
                {value["类型"] for value in battle_snapshot.techniques[3:]},
                {"附魔", "宝石"},
            )
            original_loadout = deepcopy(
                (
                    partner.direction_id,
                    partner.aptitude,
                    partner.techniques,
                    partner.enchantments,
                    partner.gems,
                )
            )

            self.assertEqual(services.npc.leave(user_id, npc_id).status, "left_party")
            self.assertEqual(services.npc.invite(user_id, npc_id).status, "invited")
            rejoined = services.npc.partner(user_id, npc_id)
            self.assertIsNotNone(rejoined)
            assert rejoined is not None
            self.assertEqual(
                (
                    rejoined.direction_id,
                    rejoined.aptitude,
                    rejoined.techniques,
                    rejoined.enchantments,
                    rejoined.gems,
                ),
                original_loadout,
            )

            self.assertEqual(services.location.move(user_id, "朔风原").status, "moved")
            self.assertEqual(
                [value.npc_id for value in services.npc.at_location(user_id, "朔风原")],
                [npc_id],
            )
            self.assertNotIn(
                npc_id,
                [value.npc_id for value in services.npc.at_location(user_id, "青溪村")],
            )
            services.exploration.seed_factory = lambda: 7
            started = services.exploration.start(user_id)
            self.assertEqual(started.status, "started")
            self.assertEqual(started.partners, (npc_id,))
            clock.advance(600)
            exploration = services.exploration.end(user_id)
            self.assertIsNotNone(exploration)
            assert exploration is not None
            self.assertEqual(exploration.completed_rounds, 1)
            self.assertEqual(exploration.partners, (npc_id,))
            if exploration.victories:
                terrain_items = set(
                    services.content.items_in_groups(
                        list(
                            services.content.location_definitions["朔风原"][
                                "天材地宝池"
                            ]
                        )
                    )
                )
                self.assertTrue(
                    any(
                        (services.player.resolve_item(item_name) or ("", ""))[0]
                        in terrain_items
                        for item_name in exploration.drops
                    )
                )
            explored_partner = services.npc.partner(user_id, npc_id)
            self.assertIsNotNone(explored_partner)
            assert explored_partner is not None
            self.assertEqual(explored_partner.stamina, 50)
            self.assertEqual(explored_partner.weapon["经验"], exploration.weapon_experience)

            self.assertEqual(services.location.move(user_id, "青溪村").status, "moved")
            services.seclusion.seed_factory = lambda: 4
            self.assertEqual(services.seclusion.start(user_id), "started")
            clock.advance(600)
            seclusion = services.seclusion.end(user_id)
            self.assertIsNotNone(seclusion)
            assert seclusion is not None
            self.assertEqual(len(seclusion.partners), 1)
            self.assertEqual(seclusion.partners[0].npc_id, npc_id)
            self.assertEqual(seclusion.partners[0].experience, seclusion.experience)
            recovered_partner = services.npc.partner(user_id, npc_id)
            self.assertIsNotNone(recovered_partner)
            assert recovered_partner is not None
            self.assertGreater(recovered_partner.stamina, explored_partner.stamina)
            profile = services.npc.nearby_profile(user_id, npc_id)
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertEqual(profile.level, recovered_partner.level)
            self.assertEqual(profile.directions, (recovered_partner.direction_id,))

    def test_temporary_database_small_loop(self) -> None:
        clock = MutableClock()
        with TemporaryDirectory() as directory:
            services = build_game_services(
                data_dir=ROOT / "data",
                database_path=Path(directory) / "game.db",
                clock=clock,
            )
            services.seclusion.seed_factory = lambda: 10
            self.assertEqual(services.seclusion.start("user-1", "晓楠"), "started")
            clock.advance(600)
            seclusion = services.seclusion.end("user-1")
            self.assertIsNotNone(seclusion)
            assert seclusion is not None
            self.assertEqual(seclusion.completed_rounds, 1)
            self.assertEqual(len(seclusion.techniques), 1)
            technique = seclusion.techniques[0]
            self.assertIn(technique.technique_id, services.content.technique_definitions)
            self.assertEqual(
                services.player.equip_technique("user-1", technique.born_order, 1),
                "equipped",
            )
            self.assertEqual(services.location.move("user-1", "朔风原").status, "moved")

            services.exploration.seed_factory = lambda: 7
            started = services.exploration.start("user-1", "晓楠")
            self.assertEqual(started.status, "started")
            clock.advance(600)
            settlement = services.exploration.end("user-1")
            self.assertIsNotNone(settlement)
            assert settlement is not None
            self.assertEqual(settlement.completed_rounds, 1)
            self.assertEqual(settlement.victories + settlement.defeats, 1)
            self.assertIn(
                settlement.encounters[0]["enemy"],
                services.location.state("朔风原").enemies,
            )
            encountered = services.content.enemy_definitions[
                settlement.encounters[0]["enemy"]
            ]
            self.assertGreaterEqual(
                settlement.encounters[0]["enemy_level"],
                encountered["等级"][0],
            )
            self.assertLessEqual(
                settlement.encounters[0]["enemy_level"],
                encountered["等级"][1],
            )
            assets = services.player.load("user-1")
            self.assertEqual(assets.player.stamina, 50)
            self.assertEqual(assets.weapon.experience, settlement.weapon_experience)
            self.assertEqual(assets.player.spirit_stones, 100 + settlement.spirit_stones)


if __name__ == "__main__":
    unittest.main()
