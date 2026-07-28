from __future__ import annotations

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
from game.cmd.功法.service import _mechanism_text
from game.content import GameContent, GameContentError, _validate
from game.core import JsonDataReader
from game.rules import BattleEngine, CombatantSnapshot
from game.rules.battle import BattleContext, DamageRequest, Fighter


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
        cls.player_attributes = dict(cls.content.player["人物"]["属性"])

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
        player.passives = passives
        context = BattleContext(
            rng=random.Random(7),
            left=player,
            right=enemy,
            item_definitions={},
        )
        context.engine = self.engine
        return context

    def technique(self, name: str, born_order: int) -> dict:
        definition = self.content.technique_definitions[name]
        return {
            "实例": f"test-{born_order}",
            "功法": name,
            "品级": "凡品",
            "出生序号": born_order,
            "威力倍率": 1.0,
            "词条": [],
            "能力": [dict(value) for value in definition.get("组成") or ()],
        }

    def npc_snapshot(
        self,
        enemy_id: str,
        seed: int,
        *,
        content: GameContent | None = None,
        definition: dict | None = None,
    ) -> CombatantSnapshot:
        configured = content or self.content
        opponent = definition or configured.npc_definitions[enemy_id]
        return CombatantSnapshot(
            id=f"opponent:{seed}",
            name=enemy_id,
            attributes=opponent["人物"]["属性"],
            weapon_attack=float(opponent["本命武器"]["攻击"]),
            techniques=tuple(
                configured.configured_battle_techniques(
                    opponent["功法"],
                    instance_prefix=f"opponent:{seed}",
                )
            ),
            medicine_threshold=float(opponent["战斗策略"]["用药阈值"]),
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
        opponent = enemy or self.content.npc_definitions[enemy_id]
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
            right=self.npc_snapshot(
                enemy_id,
                seed,
                definition=opponent,
            ),
            item_definitions=self.content.item_definitions,
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
        combat["机制"]["错误复生"] = {"能力": "复活"}
        with self.assertRaisesRegex(GameContentError, "未知原子能力 复活"):
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
        technique_definition = {
            "说明": "只由已登记规则组合出的测试功法。",
            "随机词条": list(self.content.affix_definitions)[:4],
            "组成": [
                {"能力": "固定属性加成", "属性": {"攻击": 3}},
                {
                    "能力": "主动技能",
                    "名称": "灵焰式",
                    "精神消耗": 0,
                    "冷却回合": 0,
                    "效果": [{"能力": "引用战斗机制", "机制": "试制灵焰"}],
                },
            ],
        }
        with TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            shutil.copytree(ROOT / "data" / "rules", data_dir / "rules")
            shutil.copytree(ROOT / "data" / "content", data_dir / "content")
            changes = (
                (data_dir / "rules" / "原子能力.json", "原子能力", "灵焰冲击", alias),
                (data_dir / "content" / "机制.json", "机制", "试制灵焰", mechanism),
                (data_dir / "content" / "功法.json", "功法", "试制功法", technique_definition),
            )
            for path, section, key, value in changes:
                data = json.loads(path.read_text(encoding="utf-8"))
                data[section][key] = value
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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
            right=self.npc_snapshot("石门守修", 11, content=configured),
            item_definitions=configured.item_definitions,
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
        enemy = deepcopy(self.content.npc_definitions["山道劫修"])
        enemy["人物"]["属性"].update({"血气上限": 1000, "速度": 1})
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
            right=self.npc_snapshot("山道劫修", 9, definition=enemy),
            item_definitions=self.content.item_definitions,
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

    def test_equipped_techniques_rotate_and_multi_hit_is_atomic(self) -> None:
        expected_efficiency = {25: 0.4, 70: 14 / 17, 100: 1.0, 200: 4 / 3, 500: 5 / 3}
        for speed, expected in expected_efficiency.items():
            self.assertAlmostEqual(self.engine._action_efficiency(speed), expected)

        names = list(self.content.technique_definitions)
        outcome = self.simulate(names)
        used = {event.values.get("技能") for event in outcome.events if event.kind == "skill"}
        self.assertTrue({"离火引诀", "星枢回转", "三叩天门"}.issubset(used))
        hits = [
            event
            for event in outcome.events
            if event.kind == "damage" and event.mechanism == "踏罡三叩"
        ]
        self.assertGreaterEqual(len(hits), 3)
        self.assertEqual(
            [event.text.split("造成", 1)[0] for event in hits[:3]],
            ["踏罡一叩", "踏罡二叩", "踏罡三叩"],
        )

    def test_periodic_damage_probability_source_and_display(self) -> None:
        fire = self.simulate(["离火归元诀"])
        self.assertTrue(
            any(
                event.text.startswith("离火灼身") and event.mechanism == "离火灼身"
                for event in fire.events
            )
        )
        self.assertTrue(any(event.mechanism == "火里栽莲" and event.kind == "recover" for event in fire.events))
        self.assertFalse(any(event.kind == "状态造成伤害" for event in fire.events))

        applied = self.simulate(seed=3, action_limit=2, enemy_id="密林火修")
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

    def test_same_technique_executes_identically_on_both_sides(self) -> None:
        technique = self.technique("离火归元诀", 1)
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
            item_definitions=self.content.item_definitions,
            seed=77,
            action_limit=1,
        )
        right_run = self.engine.simulate(
            left=snapshot("left-dummy", fighter=False),
            right=snapshot("right-cultivator", fighter=True),
            item_definitions=self.content.item_definitions,
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

    def test_roadside_npc_uses_own_medicine_and_only_drops_inventory(self) -> None:
        npc_definition = self.content.npc_definitions["山道劫修"]
        self.assertNotIn("本命武器", npc_definition["纳戒"])
        left_attributes = dict(self.player_attributes)
        left_attributes.update({"攻击": 20, "速度": 200})
        right_attributes = dict(self.player_attributes)
        right_attributes.update({"血气上限": 100, "速度": 100})
        outcome = self.engine.simulate(
            left=CombatantSnapshot(
                id="player",
                name="玩家",
                attributes=left_attributes,
                health=100,
                spirit=60,
            ),
            right=CombatantSnapshot(
                id="npc",
                name="路边修士",
                attributes=right_attributes,
                health=100,
                spirit=60,
                inventory={"小还丹": 1, "踏罡残页": 1},
                auto_medicine=True,
                medicine_threshold=1.0,
            ),
            item_definitions=self.content.item_definitions,
            seed=23,
            action_limit=2,
        )
        self.assertEqual(outcome.right.consumed_items, {"小还丹": 1})
        self.assertEqual(outcome.right.inventory, {"踏罡残页": 1})

        with TemporaryDirectory() as directory:
            services = build_game_services(
                data_dir=ROOT / "data",
                database_path=Path(directory) / "game.db",
            )
            initial_assets = services.player.load("npc-loot-test")
            original_weapon = initial_assets.weapon.name
            original_medicine = initial_assets.inventory.get("小还丹", 0)
            services.location.move("npc-loot-test", "青岚山脚")
            nearby = services.npc.nearby("npc-loot-test")
            self.assertEqual([value.npc_id for value in nearby], ["山道劫修"])
            spoken = services.npc.talk("npc-loot-test", "山道劫修", seed=1)
            self.assertIsNotNone(spoken)
            with services.database.transaction(write=True) as connection:
                services.exploration._apply_rewards(
                    connection,
                    "npc-loot-test",
                    [
                        {
                            "result": "victory",
                            "consumed_items": {},
                            "npc_spirit_stones": 9,
                            "weapon_experience": 5,
                            "npc_inventory": dict(outcome.right.inventory),
                        }
                    ],
                )
            assets = services.player.load("npc-loot-test")
            self.assertEqual(assets.inventory.get("踏罡残页"), 1)
            self.assertEqual(assets.inventory.get("小还丹", 0), original_medicine)
            self.assertEqual(assets.weapon.name, original_weapon)

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

    def test_temporary_database_small_loop(self) -> None:
        clock = MutableClock()
        with TemporaryDirectory() as directory:
            services = build_game_services(
                data_dir=ROOT / "data",
                database_path=Path(directory) / "game.db",
                clock=clock,
            )
            services.seclusion.seed_factory = lambda: 4
            self.assertEqual(services.seclusion.start("user-1", "晓楠"), "started")
            clock.advance(600)
            seclusion = services.seclusion.end("user-1")
            self.assertIsNotNone(seclusion)
            assert seclusion is not None
            self.assertEqual(seclusion.completed_rounds, 1)
            self.assertEqual(len(seclusion.techniques), 1)
            technique = seclusion.techniques[0]
            self.assertEqual(technique.technique_id, "离火归元诀")
            self.assertEqual(
                services.player.equip_technique("user-1", technique.born_order, 1),
                "equipped",
            )
            self.assertEqual(services.location.move("user-1", "青岚山脚").status, "moved")

            services.exploration.seed_factory = lambda: 7
            started = services.exploration.start("user-1", "晓楠")
            self.assertEqual(started.status, "started")
            clock.advance(600)
            settlement = services.exploration.end("user-1")
            self.assertIsNotNone(settlement)
            assert settlement is not None
            self.assertEqual(settlement.completed_rounds, 1)
            self.assertEqual(settlement.victories, 1)
            assets = services.player.load("user-1")
            self.assertEqual(assets.player.stamina, 50)
            self.assertEqual(assets.weapon.experience, settlement.weapon_experience)
            self.assertEqual(assets.player.spirit_stones, 100 + settlement.spirit_stones)


if __name__ == "__main__":
    unittest.main()
