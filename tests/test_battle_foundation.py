from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import random
import unittest

from game.rules import BattleEngine, CombatantSnapshot
from game.rules.battle import BattleContext, Fighter, Skill, StatusState, load_battle_foundation, validate_battle_foundation


ROOT = Path(__file__).resolve().parents[1]


def target(scope: str, **values):
    return {"能力": "选择目标", "范围": scope, **values}


def number(value: float):
    return {"能力": "读取数值", "来源": "固定值", "固定值": value}


class BattleFoundationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = load_battle_foundation(ROOT / "data")

    def engine(self, rules=None) -> BattleEngine:
        return BattleEngine(deepcopy(rules or self.rules))

    @staticmethod
    def fighter(identity: str, name: str, *, health=100, spirit=100, side=0, kind="修士"):
        return Fighter(
            id=identity,
            name=name,
            attributes={"血气上限": 100, "精神上限": 100, "护盾上限": 100, "攻击": 10, "防御": 0, "速度": 100},
            health=health,
            spirit=spirit,
            side=side,
            kind=kind,
            controller_id=identity,
        )

    def context(self, engine, left, right):
        context = BattleContext(
            rng=random.Random(7),
            left=left[0],
            right=right[0],
            item_definitions={},
            left_team=list(left),
            right_team=list(right),
        )
        context.engine = engine
        context.action_progress = {fighter.id: 0 for fighter in context.fighters}
        return context

    def test_foundation_declares_exact_executable_boundary(self):
        self.assertEqual(len(self.rules["原子能力"]), 68)
        self.assertEqual(len(self.rules["事件"]), 57)
        self.assertEqual(len(self.rules["机制"]), 1600)
        self.assertEqual(len(self.rules["机制名称"]), 1600)
        self.assertEqual(self.rules["机制名称"]["600001"], "正锋")
        text = json.dumps(self.rules["原子能力"], ensure_ascii=False)
        self.assertNotIn("蓄势", text)
        self.assertNotIn("选择自身", self.rules["原子能力"])
        self.assertNotIn("状态周期触发", self.rules["原子能力"])
        engine = self.engine()
        routed = set(engine._mechanism_handlers) | set(engine._condition_handlers) | set(engine._value_handlers) | set(engine._target_handlers) | set(engine._skill_selector_handlers) | set(engine._assembly_handlers) | {"选择状态"}
        for name, definition in self.rules["原子能力"].items():
            self.assertIn(definition["执行器"], routed, name)

    def test_mechanism_library_is_numbered_curated_and_covers_all_non_assembly_atoms(self):
        directory = ROOT / "data" / "内容" / "战斗机制"
        files = sorted(directory.glob("*.json"))
        self.assertEqual(len(files), 80)
        entries = [
            entry
            for path in files
            for entry in json.loads(path.read_text(encoding="utf-8"))
        ]
        self.assertTrue(all(len(json.loads(path.read_text(encoding="utf-8"))) == 20 for path in files))
        self.assertEqual(
            {entry["编号"] for entry in entries},
            {f"60{index:04d}" for index in range(1, 1601)},
        )
        self.assertEqual(len({entry["名称"] for entry in entries}), 1600)
        self.assertTrue(all(set(entry) == {"编号", "名称", "节点"} for entry in entries))

        used: set[str] = set()

        def collect(value):
            if isinstance(value, dict):
                if "能力" in value:
                    used.add(str(value["能力"]))
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(entries)
        self.assertEqual(
            set(self.rules["原子能力"]) - used,
            {"固定属性加成", "主动技能", "被动技能", "引用被动机制"},
        )

    def test_mechanisms_have_no_inert_battle_rules_or_colliding_runtime_names(self):
        entries = [
            entry
            for path in sorted((ROOT / "data" / "内容" / "战斗机制").glob("*.json"))
            for entry in json.loads(path.read_text(encoding="utf-8"))
        ]
        statuses = {}
        forms = {}

        def visit(value, listener_event=None):
            if isinstance(value, dict):
                current_event = (
                    str(value.get("事件") or "")
                    if value.get("能力") == "监听事件"
                    else listener_event
                )
                if value.get("能力") == "修改战场规则" and value.get("方式") == "添加":
                    rule = value.get("规则")
                    self.assertEqual(set(rule), {"监听"})
                    self.assertTrue(rule["监听"])
                if value.get("能力") == "修改行动意图":
                    self.assertEqual(current_event, "行动决策前")
                if value.get("能力") == "添加状态":
                    definition = value["状态"]
                    signature = json.dumps(definition, ensure_ascii=False, sort_keys=True)
                    previous = statuses.setdefault(definition["名称"], signature)
                    self.assertEqual(previous, signature, definition["名称"])
                if value.get("能力") == "切换形态":
                    signature = json.dumps(value.get("定义") or {}, ensure_ascii=False, sort_keys=True)
                    previous = forms.setdefault(value["形态"], signature)
                    self.assertEqual(previous, signature, value["形态"])
                for child in value.values():
                    visit(child, current_event)
            elif isinstance(value, list):
                for child in value:
                    visit(child, listener_event)

        visit(entries)

    def test_each_mechanism_domain_reaches_the_runtime_by_stable_id(self):
        engine = self.engine()
        actor = self.fighter("actor", "本体", health=50, spirit=20)
        ally = self.fighter("ally", "同伴")
        enemy = self.fighter("enemy", "敌方", side=1)
        actor.skills = [Skill("test", "试诀", spirit_cost=20, cooldown_actions=2)]
        actor.current_skill = "test"
        context = self.context(engine, (actor, ally), (enemy,))

        enemy_health = enemy.health
        engine._execute_mechanism_reference(context, actor, enemy, "600001")
        self.assertLess(enemy.health, enemy_health)
        engine._execute_mechanism_reference(context, actor, enemy, "600025")
        self.assertGreater(actor.health, 50)
        engine._execute_mechanism_reference(context, actor, enemy, "600037")
        self.assertTrue(any(status.name == "蚀脉" for status in enemy.statuses))
        engine._execute_mechanism_reference(context, actor, enemy, "600049")
        self.assertGreater(actor.spirit, 20)
        engine._execute_mechanism_reference(context, actor, enemy, "600061")
        self.assertGreater(context.action_progress[actor.id], 0)
        engine._execute_mechanism_reference(context, actor, enemy, "600073")
        self.assertTrue(context.judgement_overrides["命中"])
        engine._execute_mechanism_reference(context, actor, enemy, "600085")
        self.assertEqual(actor.skills[0].spirit_cost, 15)
        engine._execute_mechanism_reference(context, actor, enemy, "600097")
        self.assertEqual(context.relations[0]["名称"], "同契")
        engine._execute_mechanism_reference(context, actor, enemy, "600109")
        self.assertTrue(any(fighter.summoned for fighter in context.fighters))
        engine._execute_mechanism_reference(context, actor, enemy, "600121")
        self.assertEqual(actor.form, "攻势")

        actor.passives = [
            {"机制": identity, "结算顺序": order, "节点": self.rules["机制"][identity]}
            for order, identity in enumerate(("600020", "600133"), start=1)
        ]
        engine._dispatch_event(
            context,
            kind="受到伤害后",
            source=enemy,
            target=actor,
            amount=20,
            values={"实际数值": 20, "护盾伤害": 0, "血气伤害": 20, "过量伤害": 0, "伤害形式": "直接"},
        )
        self.assertEqual(context.mechanism_counters[(actor.id, "创势")], 2)
        self.assertEqual(context.records[(actor.id, "最近受伤")], [20.0])
        self.assertEqual(engine.catalog.mechanism_name("600001"), "正锋")

    def test_new_ecosystem_signatures_match_names_and_execute(self):
        engine = self.engine()
        actor = self.fighter("actor", "本体", health=30, spirit=80)
        enemy = self.fighter("enemy", "敌方", health=80, side=1)
        actor.skills = [Skill("origin", "祖传剑诀", spirit_cost=5, cooldown_actions=1)]
        actor.current_skill = "origin"
        context = self.context(engine, (actor,), (enemy,))

        engine._execute_mechanism_reference(context, actor, enemy, "600901")
        self.assertEqual((actor.health, enemy.health), (80, 30))

        engine._execute_mechanism_reference(context, actor, enemy, "601461")
        self.assertTrue(any(value.kind == "构造物" for value in context.fighters))

        engine._execute_mechanism_reference(context, actor, enemy, "601361")
        self.assertGreater(len(actor.skills), 1)

        actor.passives = [{"机制": "601581", "结算顺序": 1, "节点": self.rules["机制"]["601581"]}]
        engine._dispatch_event(context, kind="行动决策后", source=enemy, target=actor)
        self.assertEqual(context.records[(actor.id, "敌行兆")], [1.0])

    def test_foundation_rejects_invalid_timing_and_reaction_contracts(self):
        invalid_timing = deepcopy(self.rules)
        invalid_timing["行动规则"]["事件链深度上限"] = 0
        with self.assertRaisesRegex(ValueError, "事件链深度上限必须是正整数"):
            validate_battle_foundation(invalid_timing)
        invalid_reaction = deepcopy(self.rules)
        invalid_reaction["状态反应"] = [{"名称": "伪反应", "需要状态": ["火"]}]
        with self.assertRaisesRegex(ValueError, "需要状态至少两项"):
            validate_battle_foundation(invalid_reaction)
        with self.assertRaisesRegex(ValueError, "剩余回合"):
            StatusState.from_dict({"名称": "旧状态", "剩余回合": 2})

    def test_listener_distinguishes_ally_and_enemy_critical_sources(self):
        engine = self.engine()
        owner = self.fighter("owner", "本体")
        ally = self.fighter("ally", "道侣")
        enemy = self.fighter("enemy", "敌方", side=1)
        owner.passives = [
            {
                "机制": "友方暴击留痕",
                "结算顺序": 1,
                "节点": {
                    "能力": "监听事件", "事件": "暴击后", "观察角色": "来源", "阵营关系": "其他己方",
                    "效果": [{"能力": "记录战斗事实", "名称": "友方暴击", "值": 1, "方式": "累加"}],
                },
            },
            {
                "机制": "敌方暴击留痕",
                "结算顺序": 2,
                "节点": {
                    "能力": "监听事件", "事件": "暴击后", "观察角色": "来源", "阵营关系": "任意敌方",
                    "效果": [{"能力": "记录战斗事实", "名称": "敌方暴击", "值": 1, "方式": "累加"}],
                },
            },
        ]
        context = self.context(engine, (owner, ally), (enemy,))
        engine._dispatch_event(context, kind="暴击后", source=ally, target=enemy, amount=10)
        engine._dispatch_event(context, kind="暴击后", source=enemy, target=owner, amount=10)
        self.assertEqual(context.records[(owner.id, "友方暴击")], [1.0])
        self.assertEqual(context.records[(owner.id, "敌方暴击")], [1.0])

    def test_event_mutation_reduces_enemy_healing_before_settlement(self):
        engine = self.engine()
        healer = self.fighter("healer", "治疗者", health=10)
        counter = self.fighter("counter", "截脉者", side=1)
        counter.passives = [{
            "机制": "截断恢复", "结算顺序": 1,
            "节点": {
                "能力": "监听事件", "事件": "恢复前", "观察角色": "承受者", "阵营关系": "任意敌方",
                "效果": [{"能力": "修改事件数值", "方式": "乘算", "数值": 50}],
            },
        }]
        context = self.context(engine, (healer,), (counter,))
        ok = engine._execute_mechanism(
            context, healer, healer,
            {"能力": "恢复资源", "目标": target("自身"), "资源": "血气", "数值": number(80)},
        )
        self.assertTrue(ok)
        self.assertEqual(healer.health, 50)

    def test_declared_skill_recovery_shield_and_control_attributes_settle(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者", health=10)
        target_fighter = self.fighter("target", "承受者", health=10, side=1)
        actor.attributes.update({"治疗加成": 50, "护盾加成": 20, "技能威力": 100, "控制命中率": 0})
        target_fighter.attributes.update({"受疗加成": 20, "受盾加成": 25, "韧性": 50, "控制抵抗率": 0})
        context = self.context(engine, (actor,), (target_fighter,))
        engine._execute_mechanism(context, actor, target_fighter, {"能力": "恢复资源", "目标": target("当前目标"), "资源": "血气", "数值": 10})
        engine._execute_mechanism(context, actor, target_fighter, {"能力": "恢复资源", "目标": target("当前目标"), "资源": "护盾", "数值": 10})
        skill = Skill("skill", "术式", effects=({"能力": "造成伤害", "目标": target("当前目标"), "数值": 10, "能否暴击": False, "能否格挡": False},))
        actor.skills.append(skill)
        engine._cast_skill(context, actor, target_fighter, skill)
        engine._execute_mechanism(context, actor, target_fighter, {
            "能力": "添加状态", "目标": target("当前目标"),
            "状态": {"名称": "定身", "类别": "负面", "标签": ["控制"], "是否控制": True, "控制基础命中率": 100, "剩余行动": 4, "行动限制": ["行动"]},
        })
        self.assertEqual(target_fighter.health, 23)
        self.assertEqual(target_fighter.shield, 0)
        self.assertEqual(target_fighter.statuses[0].remaining_turns, 2)

    def test_random_skill_selection_uses_battle_rng_and_resource_cost_can_redirect(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者", spirit=50)
        ally = self.fighter("ally", "代偿者", spirit=50)
        enemy = self.fighter("enemy", "敌人", side=1)
        actor.skills = [Skill(f"s{i}", f"术式{i}", born_order=i) for i in range(1, 4)]
        ally.passives = [{"机制": "代偿", "节点": {
            "能力": "监听事件", "事件": "资源消耗前", "观察角色": "承受者", "阵营关系": "其他己方",
            "效果": [{"能力": "修改事件目标", "目标": target("自身")}],
        }}]
        context = self.context(engine, (actor, ally), (enemy,))
        expected = ["s1", "s2", "s3"]
        expected_rng = random.Random(7)
        expected_rng.shuffle(expected)
        chosen = engine._select_skills(context, actor, {"能力": "选择技能", "范围": "全部技能", "排序": "随机", "选择全部": True})
        self.assertEqual(chosen, expected)
        engine._execute_mechanism(context, actor, enemy, {"能力": "消耗资源", "目标": target("自身"), "资源": "精神", "数值": 10})
        self.assertEqual(actor.spirit, 50)
        self.assertEqual(ally.spirit, 40)

    def test_transaction_rolls_back_every_partial_cost(self):
        engine = self.engine()
        actor = self.fighter("actor", "施法者", spirit=5)
        enemy = self.fighter("enemy", "敌人", side=1)
        context = self.context(engine, (actor,), (enemy,))
        success = engine._execute_mechanism(
            context, actor, enemy,
            {
                "能力": "事务执行",
                "效果": [
                    {"能力": "设置资源", "目标": target("自身"), "资源": "护盾", "数值": number(50)},
                    {"能力": "消耗资源", "目标": target("自身"), "资源": "精神", "数值": number(20), "不足时是否失败": True},
                ],
            },
        )
        self.assertFalse(success)
        self.assertEqual(actor.shield, 0)
        self.assertEqual(actor.spirit, 5)

    def test_transaction_rolls_back_rng_event_mutation_and_created_objects(self):
        engine = self.engine()
        actor = self.fighter("actor", "施法者", health=10, spirit=0)
        enemy = self.fighter("enemy", "敌人", side=1)
        actor.passives = [{
            "机制": "失败事务",
            "节点": {
                "能力": "监听事件", "事件": "恢复前", "观察角色": "承受者", "阵营关系": "自身",
                "效果": [{
                    "能力": "事务执行",
                    "效果": [
                        {"能力": "修改事件数值", "方式": "设置", "数值": 1},
                        {"能力": "随机执行", "选项": [
                            {"能力": "记录战斗事实", "名称": "随机结果", "值": 1},
                            {"能力": "记录战斗事实", "名称": "随机结果", "值": 2},
                        ]},
                        {"能力": "创建战斗对象", "类型": "参战者", "定义": {"名称": "临时剑灵", "属性": {"血气上限": 10}}},
                        {"能力": "修改判定", "判定": "暴击", "方式": "必定成功", "次数": 1},
                        {"能力": "消耗资源", "目标": target("自身"), "资源": "精神", "数值": 1, "不足时是否失败": True},
                    ],
                }],
            },
        }]
        context = self.context(engine, (actor,), (enemy,))
        expected_rng = random.Random(7)
        engine._execute_mechanism(
            context, actor, actor,
            {"能力": "恢复资源", "目标": target("自身"), "资源": "血气", "数值": 30},
        )
        self.assertEqual(actor.health, 40)
        self.assertEqual(len(context.fighters), 2)
        self.assertFalse(context.records)
        self.assertFalse(context.judgement_overrides)
        self.assertEqual(context.summon_serial, 0)
        self.assertEqual(context.rng.random(), expected_rng.random())

    def test_event_conversion_cycle_is_rejected_and_stack_is_cleaned(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        actor.passives = [
            {"机制": "恢复化盾", "节点": {
                "能力": "监听事件", "事件": "恢复前", "观察角色": "承受者", "阵营关系": "自身",
                "效果": [{"能力": "转化事件", "事件": "获得护盾前"}],
            }},
            {"机制": "护盾化恢复", "节点": {
                "能力": "监听事件", "事件": "获得护盾前", "观察角色": "承受者", "阵营关系": "自身",
                "效果": [{"能力": "转化事件", "事件": "恢复前"}],
            }},
        ]
        context = self.context(engine, (actor,), (enemy,))
        with self.assertRaisesRegex(RuntimeError, "事件转化形成循环"):
            engine._dispatch_event(context, kind="恢复前", source=actor, target=actor, amount=10)
        self.assertEqual(context.event_depth, 0)
        self.assertFalse(context.event_stack)

    def test_mechanism_reference_and_triggered_skill_have_hard_depth_limits(self):
        rules = deepcopy(self.rules)
        rules["机制"] = {"自引": {"能力": "引用战斗机制", "机制": "自引"}}
        rules["行动规则"]["能力链深度上限"] = 6
        rules["行动规则"]["触发技能嵌套上限"] = 3
        engine = self.engine(rules)
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        context = self.context(engine, (actor,), (enemy,))
        with self.assertRaisesRegex(RuntimeError, "能力链超过安全深度"):
            engine._execute_mechanism(context, actor, enemy, {"能力": "引用战斗机制", "机制": "自引"})
        self.assertEqual(context.mechanism_depth, 0)

        recursive = {"能力": "触发技能", "技能": {"能力": "选择技能", "范围": "指定技能", "名称": "回响"}, "忽略代价": True, "忽略冷却": True}
        skill = Skill("echo", "回响", effects=(recursive,))
        actor.skills.append(skill)
        self.assertFalse(engine._execute_mechanism(context, actor, enemy, recursive))
        self.assertEqual(skill.uses, 3)
        self.assertEqual(context.triggered_skill_depth, 0)

    def test_once_per_battle_skill_is_assembled_and_cannot_cast_twice(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        techniques = ({
            "实例": "秘术实例",
            "功法": "焚神秘术",
            "能力": [{
                "能力": "主动技能",
                "名称": "一念焚神",
                "精神消耗": 0,
                "冷却行动": 0,
                "使用次数": 1,
                "效果": [{
                    "能力": "造成伤害", "目标": target("当前目标"), "数值": 10,
                    "能否暴击": False, "能否格挡": False,
                }],
            }],
        },)
        skills, _ = engine._technique_rules(techniques, {})
        self.assertEqual(skills[0].use_limit, 1)
        context = self.context(engine, (actor,), (enemy,))

        self.assertTrue(engine._cast_skill(context, actor, enemy, skills[0]))
        health_after_first_cast = enemy.health
        self.assertFalse(engine._cast_skill(context, actor, enemy, skills[0]))
        self.assertEqual(skills[0].uses, 1)
        self.assertEqual(enemy.health, health_after_first_cast)

    def test_equal_release_orders_form_a_stable_rotating_sequence(self):
        engine = self.engine()

        def active(name, order, spirit=0):
            return {
                "能力": "主动技能",
                "名称": name,
                "释放顺序": order,
                "精神消耗": spirit,
                "冷却行动": 1,
                "效果": [{
                    "能力": "造成伤害",
                    "目标": target("当前目标"),
                    "数值": 1,
                    "能否暴击": False,
                    "能否格挡": False,
                }],
            }

        techniques = (
            {
                "实例": "甲",
                "编号": "400002",
                "名称": "甲功法",
                "出生序号": 2,
                "能力": [active("甲一", 1), active("甲二", 2)],
            },
            {
                "实例": "乙",
                "编号": "400001",
                "名称": "乙功法",
                "出生序号": 1,
                "能力": [active("乙一", 1), active("乙二", 2, spirit=120)],
            },
        )
        skills, _ = engine._technique_rules(techniques, {})
        self.assertEqual([skill.name for skill in skills], ["乙一", "甲一", "乙二", "甲二"])

        reordered_rules = deepcopy(self.rules)
        reordered_rules["行动规则"]["主动技能轮转"]["排序"] = [
            "物品编号", "释放顺序", "装配位序", "能力序号",
        ]
        reordered_skills, _ = self.engine(reordered_rules)._technique_rules(techniques, {})
        self.assertEqual(
            [skill.name for skill in reordered_skills],
            ["乙一", "乙二", "甲一", "甲二"],
        )

        actor = self.fighter("actor", "术者", spirit=100)
        actor.skills = list(skills)
        actor.cooldowns[skills[0].key] = 1
        selected = engine._next_skill_from_cursor(actor)
        self.assertEqual(selected.name, "甲一")

        engine._advance_skill_cursor(actor, selected)
        self.assertEqual(actor.skill_cursor, 2)
        self.assertEqual(engine._next_skill_from_cursor(actor).name, "甲二")

        engine._advance_skill_cursor(actor, skills[3])
        actor.cooldowns.clear()
        self.assertEqual(actor.skill_cursor, 0)
        self.assertEqual(engine._next_skill_from_cursor(actor).name, "乙一")

    def test_passive_ties_use_priority_then_stable_ascending_order(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        listener = {
            "能力": "监听事件",
            "事件": "战斗开始",
            "观察角色": "来源",
            "阵营关系": "自身",
            "效果": [],
        }
        actor.passives = [
            {"机制": "后结先权", "结算顺序": 4, "装配位序": 3, "物品编号": "410004", "能力序号": 0, "节点": {**listener, "优先级": 10}},
            {"机制": "同序后槽", "结算顺序": 1, "装配位序": 2, "物品编号": "410002", "能力序号": 0, "节点": dict(listener)},
            {"机制": "第二顺序", "结算顺序": 2, "装配位序": 1, "物品编号": "410003", "能力序号": 0, "节点": dict(listener)},
            {"机制": "同序前槽", "结算顺序": 1, "装配位序": 1, "物品编号": "410001", "能力序号": 0, "节点": dict(listener)},
        ]
        context = self.context(engine, (actor,), (enemy,))
        order = []

        def record_listener(runtime_context, *_args, **_kwargs):
            order.append(runtime_context.current_mechanism)
            return True

        engine._run_effects = record_listener
        engine._dispatch_event(
            context,
            kind="战斗开始",
            source=actor,
            target=actor,
            record=False,
        )
        self.assertEqual(order, ["后结先权", "同序前槽", "同序后槽", "第二顺序"])

    def test_main_actions_advance_the_persisted_skill_cursor(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        effect = {
            "能力": "造成伤害",
            "目标": target("当前目标"),
            "数值": 1,
            "能否暴击": False,
            "能否格挡": False,
        }
        actor.skills = [
            Skill("first", "第一式", release_order=1, effects=(effect,)),
            Skill("second", "第二式", release_order=1, effects=(effect,)),
        ]
        context = self.context(engine, (actor,), (enemy,))

        engine._take_action(context, actor)
        self.assertEqual((actor.skills[0].uses, actor.skills[1].uses), (1, 0))
        self.assertEqual(actor.skill_cursor, 1)

        engine._take_action(context, actor)
        self.assertEqual((actor.skills[0].uses, actor.skills[1].uses), (1, 1))
        self.assertEqual(actor.skill_cursor, 0)

    def test_conditional_mystery_triggers_once_and_can_be_baited(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        techniques = ({
            "实例": "反疗秘术实例",
            "功法": "问罪经",
            "能力": [{
                "能力": "被动技能",
                "名称": "回春问罪",
                "结算顺序": 1,
                "效果": [{
                    "能力": "监听事件",
                    "事件": "恢复后",
                    "观察角色": "来源",
                    "阵营关系": "任意敌方",
                    "每场战斗最多触发": 1,
                    "效果": [{
                        "能力": "造成伤害", "目标": target("事件来源"), "数值": 10,
                        "能否暴击": False, "能否格挡": False,
                    }],
                }],
            }],
        },)
        _, passives = engine._technique_rules(techniques, {})
        actor.passives = list(passives)
        context = self.context(engine, (actor,), (enemy,))

        engine._dispatch_event(context, kind="恢复后", source=enemy, target=enemy, amount=1)
        health_after_first_trigger = enemy.health
        engine._dispatch_event(context, kind="恢复后", source=enemy, target=enemy, amount=100)

        self.assertLess(health_after_first_trigger, 100)
        self.assertEqual(enemy.health, health_after_first_trigger)

    def test_every_formal_conditional_mystery_reaches_runtime(self):
        technique_dir = ROOT / "data" / "内容" / "物品" / "功法"
        mysteries = []
        for path in technique_dir.glob("*.json"):
            for technique in json.loads(path.read_text(encoding="utf-8")):
                for ability in technique["能力"]:
                    if ability["能力"] == "被动技能" and ability["效果"][0].get("能力") == "监听事件":
                        mysteries.append((technique["编号"], ability))
        self.assertEqual(len(mysteries), 40)

        for identity, ability in mysteries:
            with self.subTest(identity=identity, mystery=ability["名称"]):
                engine = self.engine()
                owner = self.fighter("owner", "术者", spirit=100)
                ally = self.fighter("ally", "同伴")
                enemy = self.fighter("enemy", "敌人", side=1)
                owner.skills = [Skill("origin", "本命诀", spirit_cost=0, cooldown_actions=1)]
                owner.current_skill = "origin"
                context = self.context(engine, (owner, ally), (enemy,))
                listener = deepcopy(ability["效果"][0])
                listener.pop("条件", None)
                owner.passives = [{"机制": identity, "结算顺序": 1, "节点": listener}]

                relation = listener.get("阵营关系", "自身")
                observed = owner if relation == "自身" else ally if relation == "其他己方" else enemy
                role = listener.get("观察角色", "来源")
                source = observed if role == "来源" else enemy if observed is not enemy else owner
                target_fighter = observed if role == "承受者" else owner if observed is not owner else enemy
                values = {
                    "行动者": observed.id,
                    "对象类型": "构造物",
                    "资源": "精神",
                    "变化前数值": 10,
                    "变化后数值": 0,
                    "实际数值": 10,
                    "技能": "本命诀",
                    "技能键": "origin",
                }
                engine._dispatch_event(
                    context,
                    kind=listener["事件"],
                    source=source,
                    target=target_fighter,
                    amount=10,
                    values=values,
                )
                self.assertTrue(context.battle_trigger_counts)

    def test_formal_group_arts_change_multiple_real_targets(self):
        technique_dir = ROOT / "data" / "内容" / "物品" / "功法"
        group_abilities = []
        abilities = {}
        for path in technique_dir.glob("*.json"):
            for technique in json.loads(path.read_text(encoding="utf-8")):
                for ability in technique["能力"]:
                    if ability["能力"] == "主动技能" and "群体" in ability.get("标签", ()):
                        group_abilities.append(ability)
                        abilities[ability["名称"].rsplit("·", 1)[-1]] = ability

        cases = {
            "万剑朝宗": ("enemy_health", lambda allies, enemies, context: sum(value.health < 100 for value in enemies)),
            "天罗封脉": ("enemy_status", lambda allies, enemies, context: sum(bool(value.statuses) for value in enemies)),
            "沧海横流": ("enemy_delay", lambda allies, enemies, context: sum(context.action_progress[value.id] < 0.5 for value in enemies)),
            "青莲普渡": ("ally_heal", lambda allies, enemies, context: sum(value.health > 50 for value in allies)),
            "山河同担": ("ally_shield", lambda allies, enemies, context: sum(value.shield > 0 for value in allies)),
            "流光渡众": ("ally_haste", lambda allies, enemies, context: sum(context.action_progress[value.id] > 0.5 for value in allies)),
            "法天象地": ("ally_status", lambda allies, enemies, context: sum(bool(value.statuses) for value in allies)),
        }
        self.assertEqual(len(group_abilities), 120)

        for name, (kind, changed) in cases.items():
            with self.subTest(name=name, kind=kind):
                engine = self.engine()
                owner = self.fighter("owner", "术者", health=50, spirit=200)
                allies = [owner, self.fighter("ally1", "同伴甲", health=50), self.fighter("ally2", "同伴乙", health=50)]
                enemies = [self.fighter(f"enemy{index}", f"敌人{index}", side=1) for index in range(3)]
                skills, _ = engine._technique_rules(({"实例": name, "名称": name, "能力": [abilities[name]]},), {})
                owner.skills = list(skills)
                context = self.context(engine, tuple(allies), tuple(enemies))
                context.action_progress = {fighter.id: 0.5 for fighter in context.fighters}
                engine._cast_skill(context, owner, enemies[0], skills[0])
                self.assertGreaterEqual(changed(allies, enemies, context), 2)

    def test_target_sets_and_aggregate_values_use_real_teams(self):
        engine = self.engine()
        owner = self.fighter("owner", "本体", health=90)
        low = self.fighter("low", "低血道侣", health=20, kind="道侣")
        high = self.fighter("high", "高血道侣", health=70, kind="道侣")
        enemy = self.fighter("enemy", "敌人", side=1)
        context = self.context(engine, (owner, low, high), (enemy,))
        selected = engine._select_targets(context, owner, enemy, target("己方", 排除自身=True, 排序="血气比例从低到高", 数量=1))
        self.assertEqual(selected, [low])
        total = engine._resolve_value(
            context,
            {"能力": "聚合数值", "目标": target("己方", 选择全部=True), "方式": "总和", "数值": {"能力": "读取数值", "来源": "目标当前血气", "目标": target("当前目标")}},
            owner,
            enemy,
        )
        self.assertEqual(total, 180)

    def test_status_reaction_consumes_inputs_and_generates_result(self):
        rules = deepcopy(self.rules)
        rules["状态反应"] = ({"名称": "焚毒", "需要状态": ["火", "毒"], "消耗层数": 1, "生成状态": {"名称": "焚毒", "类别": "负面", "剩余行动": 2}},)
        engine = self.engine(rules)
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "目标", side=1)
        context = self.context(engine, (actor,), (enemy,))
        for name in ("火", "毒"):
            engine._execute_mechanism(context, actor, enemy, {"能力": "添加状态", "目标": target("当前目标"), "状态": {"名称": name, "类别": "负面", "剩余行动": 3}})
        self.assertEqual([value.name for value in enemy.statuses], ["焚毒"])
        self.assertTrue(any(event.kind == "状态反应后" for event in context.events))

    def test_event_redirection_and_recovery_conversion_change_settlement(self):
        engine = self.engine()
        guardian = self.fighter("guardian", "护道者")
        ally = self.fighter("ally", "同伴", health=10)
        enemy = self.fighter("enemy", "敌人", side=1)
        guardian.passives = [{
            "机制": "护道", "结算顺序": 1,
            "节点": {
                "能力": "监听事件", "事件": "造成伤害前", "观察角色": "承受者", "阵营关系": "其他己方",
                "效果": [{"能力": "修改事件目标", "目标": target("自身")}],
            },
        }]
        ally.passives = [{
            "机制": "化生为盾", "结算顺序": 1,
            "节点": {
                "能力": "监听事件", "事件": "恢复前", "观察角色": "承受者", "阵营关系": "自身",
                "效果": [{"能力": "转化事件", "事件": "获得护盾前"}],
            },
        }]
        context = self.context(engine, (guardian, ally), (enemy,))
        engine._apply_damage(context, enemy, ally, 20, can_critical=False, can_block=False)
        engine._execute_mechanism(context, ally, ally, {"能力": "恢复资源", "目标": target("自身"), "资源": "血气", "数值": number(30)})
        self.assertEqual(guardian.health, 80)
        self.assertEqual(ally.health, 10)
        self.assertEqual(ally.shield, 30)

    def test_composition_history_and_named_results_form_real_chains(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者", spirit=0)
        first = self.fighter("first", "甲", side=1)
        second = self.fighter("second", "乙", side=1)
        context = self.context(engine, (actor,), (first, second))
        damage = {"能力": "造成伤害", "目标": target("当前目标"), "数值": number(5), "能否暴击": False, "能否格挡": False}
        engine._execute_mechanism(context, actor, first, {"能力": "遍历目标", "目标": target("敌方", 选择全部=True), "效果": [damage]})
        engine._execute_mechanism(context, actor, first, {"能力": "重复执行", "次数": 2, "效果": [damage]})
        engine._execute_mechanism(context, actor, first, {"能力": "顺序执行", "效果": [damage, {"能力": "保存结果", "名称": "末击", "来源": "上个效果"}]})
        failed = engine._execute_mechanism(context, actor, first, {
            "能力": "尝试执行",
            "尝试效果": [{"能力": "消耗资源", "目标": target("自身"), "资源": "精神", "数值": number(1), "不足时是否失败": True}],
            "失败效果": [{"能力": "记录战斗事实", "名称": "支付失败", "值": 1, "方式": "累加"}],
        })
        saved = context.saved_results["末击"]
        self.assertFalse(failed)
        self.assertEqual(first.health, 80)
        self.assertEqual(second.health, 95)
        self.assertEqual(saved["实际伤害"], 5)
        self.assertEqual(context.records[(actor.id, "支付失败")], [1.0])

    def test_triggered_skill_and_non_resource_costs_are_enforced(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        actor.statuses.append(__import__("game.rules.battle", fromlist=["StatusState"]).StatusState("剑意", stacks=2, max_stacks=5))
        skill = Skill("s1", "飞剑", effects=({"能力": "造成伤害", "目标": target("当前目标"), "数值": number(12), "能否暴击": False, "能否格挡": False},))
        actor.skills.append(skill)
        context = self.context(engine, (actor,), (enemy,))
        paid = engine._execute_mechanism(context, actor, enemy, {"能力": "支付代价", "代价类型": "状态层数", "状态": {"能力": "选择状态", "目标": target("自身"), "名称": "剑意"}, "数值": 2})
        triggered = engine._execute_mechanism(context, actor, enemy, {"能力": "触发技能", "技能": {"能力": "选择技能", "范围": "指定技能", "名称": "飞剑"}, "目标": target("当前目标")})
        self.assertTrue(paid)
        self.assertTrue(triggered)
        self.assertFalse(actor.statuses)
        self.assertEqual(enemy.health, 88)

    def test_created_objects_can_be_paid_or_removed_without_hidden_timers(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        context = self.context(engine, (actor,), (enemy,))
        engine._execute_mechanism(context, actor, enemy, {"能力": "创建战斗对象", "类型": "构造物", "定义": {"编号": "flag", "名称": "阵旗", "耐久": 5, "持续行动": 0}})
        construct = engine._select_targets(context, enemy, actor, target("敌方", 对象类型="构造物"))[0]
        engine._apply_damage(context, enemy, construct, 5, can_critical=False, can_block=False)
        self.assertNotIn("flag", context.combat_objects)
        engine._execute_mechanism(context, actor, enemy, {"能力": "创建战斗对象", "类型": "构造物", "定义": {"编号": "flag2", "名称": "阵旗", "持续行动": 0}})
        removed = engine._execute_mechanism(context, actor, enemy, {"能力": "支付代价", "代价类型": "战斗对象", "对象ID": "flag2"})
        self.assertTrue(removed)
        self.assertFalse(context.combat_objects)

    def test_object_limits_release_after_retirement_and_retirement_emits_once(self):
        rules = deepcopy(self.rules)
        rules["行动规则"]["每方召唤物上限"] = 1
        rules["行动规则"]["战斗构造物上限"] = 1
        engine = self.engine(rules)
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        context = self.context(engine, (actor,), (enemy,))
        summon = lambda identity: {"能力": "创建战斗对象", "类型": "参战者", "定义": {"编号": identity, "名称": identity, "属性": {"血气上限": 10}}}
        construct = lambda identity: {"能力": "创建战斗对象", "类型": "构造物", "定义": {"编号": identity, "名称": identity, "耐久": 5}}
        self.assertTrue(engine._execute_mechanism(context, actor, enemy, summon("s1")))
        self.assertFalse(engine._execute_mechanism(context, actor, enemy, summon("s2")))
        first = context.fighter_by_id("s1")
        engine._apply_damage(context, enemy, first, 100, can_critical=False, can_block=False)
        self.assertTrue(engine._execute_mechanism(context, actor, enemy, summon("s2")))
        self.assertTrue(engine._execute_mechanism(context, actor, enemy, construct("c1")))
        self.assertFalse(engine._execute_mechanism(context, actor, enemy, construct("c2")))
        shell = context.fighter_by_id("c1")
        engine._apply_damage(context, enemy, shell, 5, can_critical=False, can_block=False)
        self.assertFalse(engine._execute_mechanism(context, actor, enemy, {"能力": "移除战斗对象", "对象ID": "c1"}))
        retirements = [event for event in context.events if event.kind == "战斗对象退场后" and event.values.get("对象ID") == "c1"]
        self.assertEqual(len(retirements), 1)

    def test_constructs_never_act_or_keep_a_side_in_combat(self):
        engine = self.engine()
        left_attributes = {"血气上限": 20, "精神上限": 0, "攻击": 1, "防御": 0, "速度": 25}
        right_attributes = {"血气上限": 100, "精神上限": 0, "攻击": 100, "防御": 0, "速度": 200}
        technique = {"实例": "field", "能力": [{"能力": "被动技能", "效果": [{
            "能力": "监听事件", "事件": "战斗开始", "观察角色": "来源", "阵营关系": "自身",
            "效果": [{"能力": "创建战斗对象", "类型": "构造物", "定义": {"编号": "last-flag", "名称": "遗阵", "耐久": 10}}],
        }]}]}
        outcome = engine.simulate(
            left=CombatantSnapshot("left", "左", left_attributes, techniques=(technique,)),
            right=CombatantSnapshot("right", "右", right_attributes, tactic=({
                "优先级": 1, "行动": "普通攻击", "目标": target("敌方", 身份="修士"),
            },)),
            item_definitions={}, seed=5, action_limit=3,
        )
        flag = next(value for value in outcome.left_results if value.id == "last-flag")
        self.assertTrue(flag.alive)
        self.assertFalse(flag.counts_for_victory)
        self.assertEqual(outcome.winner_side, "right")
        self.assertFalse(any(event.kind == "行动开始" and event.source_id == "last-flag" for event in outcome.events))

    def test_source_lifetime_rules_are_removed_on_source_defeat(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "敌人", side=1)
        context = self.context(engine, (actor,), (enemy,))
        for name, temporary in (("暂留剑域", True), ("整场天象", False)):
            engine._execute_mechanism(context, actor, enemy, {
                "能力": "修改战场规则", "名称": name, "方式": "添加", "规则": {"监听": []},
                "来源退场时移除": temporary,
            })
        engine._apply_damage(context, enemy, actor, 1000, can_critical=False, can_block=False)
        self.assertEqual([rule["名称"] for rule in context.battle_rules], ["整场天象"])

    def test_forms_summons_constructs_ownership_and_tactics_are_runtime_state(self):
        engine = self.engine()
        actor = self.fighter("actor", "本体")
        enemy = self.fighter("enemy", "敌人", side=1)
        context = self.context(engine, (actor,), (enemy,))
        engine._execute_mechanism(context, actor, enemy, {"能力": "切换形态", "目标": target("自身"), "形态": "剑相", "定义": {"属性变化": {"攻击": 5}}})
        engine._execute_mechanism(context, actor, enemy, {"能力": "切换形态", "目标": target("自身"), "形态": "盾相", "定义": {"属性变化": {"攻击": 2}}})
        engine._execute_mechanism(context, actor, enemy, {"能力": "创建战斗对象", "类型": "参战者", "阵营": "己方", "定义": {"名称": "剑灵", "身份": "召唤物", "属性": {"血气上限": 30, "精神上限": 0, "攻击": 5, "速度": 80}}})
        engine._execute_mechanism(context, actor, enemy, {"能力": "创建战斗对象", "类型": "构造物", "阵营": "己方", "定义": {"名称": "阵旗", "持续行动": 3}})
        summon = next(value for value in context.fighters if value.summoned)
        construct = next(value for value in context.fighters if value.kind == "构造物")
        engine._execute_mechanism(context, actor, summon, {"能力": "修改归属", "目标": target("当前目标"), "字段": "阵营", "阵营": "敌方"})
        engine._execute_mechanism(context, enemy, construct, {"能力": "修改归属", "目标": target("当前目标", 对象类型="构造物"), "字段": "主人", "归属目标": target("自身")})
        engine._execute_mechanism(context, actor, actor, {"能力": "修改战术", "目标": target("自身"), "方式": "替换", "战术": [{"优先级": 10, "行动": "普通攻击"}]})
        self.assertEqual(actor.form, "盾相")
        self.assertEqual(actor.value("攻击"), 12)
        self.assertEqual(summon.side, 1)
        self.assertEqual(len(context.combat_objects), 1)
        self.assertEqual(context.combat_objects[construct.id].owner_id, enemy.id)
        self.assertEqual(actor.tactic[0]["优先级"], 10)

    def test_skill_mutation_copy_history_and_replay_change_real_results(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "目标", side=1)
        skill = Skill("s1", "飞剑", cooldown_actions=2, effects=({"能力": "造成伤害", "目标": target("当前目标"), "数值": number(10), "能否暴击": False, "能否格挡": False},))
        actor.skills.append(skill)
        context = self.context(engine, (actor,), (enemy,))
        engine._execute_mechanism(context, actor, enemy, skill.effects[0])
        engine._execute_mechanism(context, actor, enemy, {"能力": "回放效果", "范围": "自身上个效果", "目标": target("当前目标"), "倍率": 1})
        engine._execute_mechanism(context, actor, enemy, {"能力": "修改技能", "目标": target("自身"), "技能": {"能力": "选择技能", "范围": "指定技能", "名称": "飞剑"}, "字段": "冷却行动", "方式": "设置", "值": 4})
        engine._execute_mechanism(context, actor, enemy, {"能力": "复制技能", "来源目标": target("自身"), "接收目标": target("当前目标"), "技能": {"能力": "选择技能", "范围": "指定技能", "名称": "飞剑"}, "名称": "镜剑"})
        self.assertEqual(enemy.health, 80)
        self.assertEqual(skill.cooldown_actions, 4)
        self.assertEqual(enemy.skills[0].name, "镜剑")

    def test_skill_restriction_immunities_and_critical_cancel_are_executed(self):
        engine = self.engine()
        actor = self.fighter("actor", "术者")
        enemy = self.fighter("enemy", "守方", side=1)
        skill = Skill(
            "s1",
            "飞剑",
            effects=({
                "能力": "造成伤害",
                "目标": target("当前目标"),
                "数值": number(20),
                "能否暴击": True,
                "能否格挡": False,
            },),
        )
        actor.skills.append(skill)
        context = self.context(engine, (actor,), (enemy,))

        actor.statuses.append(StatusState("缄脉", action_limits=("技能",)))
        self.assertFalse(engine._cast_skill(context, actor, enemy, skill))
        self.assertEqual(enemy.health, 100)
        actor.statuses.clear()

        enemy.statuses.append(StatusState("封存", effect_immunities=("伤害", "恢复", "状态", "控制")))
        engine._execute_mechanism(context, actor, enemy, skill.effects[0])
        self.assertEqual(enemy.health, 100)
        enemy.health = 50
        engine._execute_mechanism(context, actor, enemy, {
            "能力": "恢复资源", "目标": target("当前目标"), "资源": "血气", "数值": 20,
        })
        self.assertEqual(enemy.health, 50)
        engine._execute_mechanism(context, actor, enemy, {
            "能力": "添加状态", "目标": target("当前目标"),
            "状态": {"名称": "试印", "类别": "中性", "剩余行动": 1},
        })
        self.assertEqual([value.name for value in enemy.statuses], ["封存"])

        enemy.statuses.clear()
        enemy.passives.append({"机制": "600204", "节点": self.rules["机制"]["600204"]})
        actor.attributes["暴击率"] = 100
        actor.attributes["暴击伤害"] = 300
        resolution = engine._apply_damage(
            context, actor, enemy, 10, can_critical=True, can_block=False,
        )
        self.assertFalse(resolution.critical)
        self.assertEqual(resolution.health_damage, 10)

    def test_relations_intent_judgement_and_battle_rules_are_mutable(self):
        engine = self.engine()
        actor = self.fighter("actor", "本体")
        ally = self.fighter("ally", "道侣", kind="道侣")
        enemy = self.fighter("enemy", "敌人", side=1)
        context = self.context(engine, (actor, ally), (enemy,))
        engine._execute_mechanism(context, actor, ally, {"能力": "修改战斗关联", "名称": "护道", "方式": "建立", "一方": target("自身"), "另一方": target("当前目标")})
        context.action_intent = __import__("game.rules.battle", fromlist=["ActionIntent"]).ActionIntent(actor.id, "普通攻击", enemy.id)
        engine._execute_mechanism(context, actor, ally, {"能力": "修改行动意图", "字段": "目标", "目标": target("当前目标")})
        engine._execute_mechanism(context, actor, enemy, {"能力": "修改判定", "判定": "暴击", "方式": "必定成功", "次数": 1})
        engine._execute_mechanism(context, actor, enemy, {"能力": "修改战场规则", "名称": "剑域", "方式": "添加", "规则": {"监听": []}})
        self.assertEqual(context.relations[0]["名称"], "护道")
        self.assertEqual(context.action_intent.target_id, ally.id)
        self.assertTrue(engine._judgement(context, "暴击", 0))
        self.assertEqual(context.battle_rules[0]["名称"], "剑域")

    def test_simulation_uses_only_action_bar_and_action_based_cooldown(self):
        engine = self.engine()
        attributes = {"血气上限": 100, "精神上限": 100, "攻击": 10, "防御": 0, "速度": 100}
        technique = {
            "实例": "t1",
            "能力": [{"能力": "主动技能", "名称": "一击", "释放顺序": 1, "精神消耗": 0, "冷却行动": 2, "效果": [{"能力": "造成伤害", "目标": target("当前目标"), "数值": number(10), "能否暴击": False, "能否格挡": False}]}],
        }
        outcome = engine.simulate(
            left=CombatantSnapshot("left", "左", attributes, techniques=(technique,)),
            right=CombatantSnapshot("right", "右", attributes),
            item_definitions={}, seed=3, action_limit=5,
        )
        event_names = [event.kind for event in outcome.events]
        self.assertIn("技能施放后", event_names)
        self.assertIn("技能冷却变化后", event_names)
        self.assertNotIn("蓄势", "".join(event_names))

    def test_first_action_also_comes_from_action_bar(self):
        engine = self.engine()
        slow = self.fighter("slow", "慢者")
        fast = self.fighter("fast", "快者", side=1)
        slow.attributes["速度"] = 25
        fast.attributes["速度"] = 500
        context = self.context(engine, (slow,), (fast,))
        self.assertEqual(engine._next_action_order(context), (fast,))
        self.assertGreater(context.action_progress["slow"], 0)

    def test_personal_action_profile_scales_against_multiple_enemies_without_exceeding_its_cap(self):
        engine = self.engine()
        boss = self.fighter("boss", "镇域修士")
        boss.battle_profile = {
            "行动效率上限": 3,
            "寡敌应变": {
                "每名额外敌人行动效率": 0.2,
                "行动效率增量上限": 0.6,
            },
        }
        enemies = tuple(
            self.fighter(f"enemy-{index}", f"敌人{index}", side=1)
            for index in range(4)
        )
        solo_context = self.context(engine, (boss,), (enemies[0],))
        team_context = self.context(engine, (boss,), enemies)

        solo = engine._action_efficiency(solo_context, boss)
        against_team = engine._action_efficiency(team_context, boss)

        self.assertAlmostEqual(solo, 1.0)
        self.assertAlmostEqual(against_team, 1.6)
        self.assertLessEqual(against_team, 3)

    def test_battle_profile_limits_control_stacking_and_duration(self):
        engine = self.engine()
        source = self.fighter("source", "控场者")
        target_fighter = self.fighter("target", "天灾修士", side=1)
        target_fighter.battle_profile = {
            "同时承受控制上限": 1,
            "控制持续上限": 1,
        }
        context = self.context(engine, (source,), (target_fighter,))
        first = {
            "能力": "添加状态",
            "目标": target("当前目标"),
            "状态": {
                "名称": "定身",
                "类别": "负面",
                "标签": ["控制"],
                "是否控制": True,
                "控制基础命中率": 100,
                "剩余行动": 6,
                "行动限制": ["行动"],
            },
        }
        second = deepcopy(first)
        second["状态"]["名称"] = "封脉"

        self.assertTrue(engine._execute_mechanism(context, source, target_fighter, first))
        self.assertEqual(target_fighter.statuses[0].remaining_turns, 1)
        self.assertFalse(engine._execute_mechanism(context, source, target_fighter, second))
        failure = next(event for event in reversed(context.events) if event.kind == "添加状态失败后")
        self.assertEqual(failure.values["原因"], "控制承载已满")

    def test_battle_profile_rejects_unknown_or_inert_fields(self):
        engine = self.engine()
        attributes = {"血气上限": 100, "精神上限": 0, "攻击": 1, "速度": 100}
        with self.assertRaisesRegex(ValueError, "战斗规格存在未知字段"):
            engine._build_fighter(
                CombatantSnapshot(
                    "fighter",
                    "修士",
                    attributes,
                    battle_profile={"首领光环": 1},
                )
            )


if __name__ == "__main__":
    unittest.main()
