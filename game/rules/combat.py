"""行动条与技能 CD 驱动的 JSON 战斗核心。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import copy
import math
import random
from typing import Any, Callable

from .battle.damage import DamageEngine, DamageRequest, DamageResolution
from .battle.mechanics import MechanismRuntime
from .battle.models import (
    ActionIntent,
    BattleContext,
    BattleOutcome,
    CombatCatalog,
    CombatantResult,
    CombatantSnapshot,
    Fighter,
    Skill,
    StatusState,
)


class BattleEngine(MechanismRuntime):
    """执行自动战斗；所有内容规则均来自传入的 JSON 目录。"""

    def __init__(self, combat_rules: Mapping[str, Any] | None = None) -> None:
        self.catalog = CombatCatalog.from_mapping(combat_rules)
        self.damage = DamageEngine(self.catalog.damage_rules)
        self._mechanism_handlers: dict[str, Callable[..., bool]] = {
            "顺序执行": self._mechanism_sequence,
            "条件执行": self._mechanism_conditional,
            "随机执行": self._mechanism_random,
            "遍历目标": self._mechanism_iterate,
            "重复执行": self._mechanism_repeat,
            "尝试执行": self._mechanism_attempt,
            "事务执行": self._mechanism_transaction,
            "监听事件": self._mechanism_listener,
            "引用机制": self._mechanism_reference,
            "造成伤害": self._mechanism_damage,
            "恢复资源": self._mechanism_recover_resource,
            "消耗资源": self._mechanism_consume_resource,
            "支付代价": self._mechanism_pay_cost,
            "设置资源": self._mechanism_set_resource,
            "转移资源": self._mechanism_transfer_resource,
            "添加状态": self._mechanism_add_status,
            "移除状态": self._mechanism_remove_status,
            "修改状态层数": self._mechanism_modify_status_stacks,
            "修改状态持续": self._mechanism_modify_status_duration,
            "复制状态": self._mechanism_copy_status,
            "转移状态": self._mechanism_transfer_status,
            "修改行动条": self._mechanism_modify_action_progress,
            "修改技能冷却": self._mechanism_modify_cooldown,
            "修改机制计量": self._mechanism_modify_counter,
            "追加攻击": self._mechanism_additional_attack,
            "分摊伤害": self._mechanism_share_damage,
            "转移伤害": self._mechanism_transfer_damage,
            "抵挡致命伤害": self._mechanism_fatal_guard,
            "复活": self._mechanism_revive,
            "修改事件数值": self._mechanism_modify_event_value,
            "修改事件目标": self._mechanism_modify_event_target,
            "修改事件标签": self._mechanism_modify_event_tags,
            "取消事件": self._mechanism_cancel_event,
            "触发技能": self._mechanism_trigger_skill,
            "记录战斗事实": self._mechanism_record_fact,
            "修改战斗关联": self._mechanism_modify_relation,
            "修改技能": self._mechanism_modify_skill,
            "复制技能": self._mechanism_copy_skill,
            "修改行动意图": self._mechanism_modify_intent,
            "转化事件": self._mechanism_transform_event,
            "修改判定": self._mechanism_modify_judgement,
            "修改战场规则": self._mechanism_modify_battle_rule,
            "保存结果": self._mechanism_save_result,
            "切换形态": self._mechanism_switch_form,
            "创建战斗对象": self._mechanism_create_object,
            "移除战斗对象": self._mechanism_remove_object,
            "修改归属": self._mechanism_modify_ownership,
            "回放效果": self._mechanism_replay_effect,
            "修改战术": self._mechanism_modify_tactic,
        }
        self._condition_handlers = {
            "概率条件": self._condition_probability,
            "数值条件": self._condition_numeric,
            "状态条件": self._condition_status,
            "类型条件": self._condition_type,
            "组合条件": self._condition_combined,
            "标签条件": self._condition_tags,
        }
        self._value_handlers = {
            "读取数值": self._value_read,
            "计算数值": self._value_calculate,
            "随机数值": self._value_random,
            "聚合数值": self._value_aggregate,
        }
        self._target_handlers = {"选择目标": self._target_select}
        self._skill_selector_handlers = {"选择技能": self._skills_select}
        self._assembly_handlers = {
            "装配属性": self._assemble_attributes,
            "装配主动技能": self._assemble_active_skill,
            "装配被动技能": self._assemble_passive_skill,
        }

    def simulate(self, *, left, right, item_definitions, seed, action_limit) -> BattleOutcome:
        return self.simulate_teams(
            left=(left,), right=(right,), item_definitions=item_definitions,
            seed=seed, action_limit=action_limit,
        )

    def simulate_teams(
        self,
        *,
        left: tuple[CombatantSnapshot, ...],
        right: tuple[CombatantSnapshot, ...],
        item_definitions: dict[str, dict[str, Any]],
        seed: int,
        action_limit: int,
        share_left_inventory: bool = False,
    ) -> BattleOutcome:
        if not left or not right:
            raise ValueError("战斗双方都必须至少有一名参战者")
        ids = [str(value.id).strip() for value in (*left, *right)]
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            raise ValueError("参战者 ID 必须非空且不可重复")
        left_fighters = [self._build_fighter(value) for value in left]
        right_fighters = [self._build_fighter(value) for value in right]
        if share_left_inventory:
            for fighter in left_fighters[1:]:
                fighter.inventory = left_fighters[0].inventory
        context = BattleContext(
            rng=random.Random(int(seed)),
            left=left_fighters[0],
            right=right_fighters[0],
            item_definitions=item_definitions,
            left_team=left_fighters,
            right_team=right_fighters,
        )
        context.engine = self
        context.action_progress = {fighter.id: 0.0 for fighter in context.fighters}
        context.event(
            "战斗开始", context.left, context.right,
            f"{'、'.join(value.name for value in left_fighters)}与{'、'.join(value.name for value in right_fighters)}进入战斗",
            values={"左方": [value.id for value in left_fighters], "右方": [value.id for value in right_fighters]},
        )
        while context.both_sides_alive and context.action_number < max(1, int(action_limit)):
            order = self._next_action_order(context)
            for actor in order:
                if not actor.alive or not context.both_sides_alive:
                    continue
                context.action_number += 1
                context.trigger_counts.clear()
                context.saved_results.clear()
                self._take_action(context, actor)
                if context.action_number >= max(1, int(action_limit)):
                    break
        left_alive = [value for value in context.left_team if value.alive and value.counts_for_victory]
        right_alive = [value for value in context.right_team if value.alive and value.counts_for_victory]
        draw = bool(left_alive) == bool(right_alive)
        context.event(
            "战斗结束", context.left, context.right,
            "战斗未分胜负" if draw else f"{'、'.join(value.name for value in left_alive or right_alive)}取胜",
            values={"结果": "未分胜负" if draw else "分出胜负", "行动数": context.action_number},
        )
        left_results = tuple(self._fighter_result(value) for value in context.left_team)
        right_results = tuple(self._fighter_result(value) for value in context.right_team)
        return BattleOutcome(
            left=left_results[0], right=right_results[0], actions=context.action_number,
            events=tuple(context.events),
            trigger_activations=sum(context.battle_trigger_counts.values()),
            left_team=left_results, right_team=right_results,
        )

    def _take_action(self, context: BattleContext, actor: Fighter) -> None:
        target = context.opponent_of(actor)
        context.event("行动开始", actor, actor, f"{actor.name}开始行动", values={"行动": context.action_number, "行动者": actor.id})
        self._recover_at_action_start(context, actor)
        self._tick_cooldowns(context, actor)
        if not self._action_restricted(actor, "使用丹药"):
            self._use_medicine(context, actor)
        intent = self._decide_action(context, actor, target)
        context.action_intent = intent
        planned_target = context.fighter_by_id(intent.target_id) or target
        decision = context.event("行动决策前", actor, planned_target, f"{actor.name}准备行动", values={"行动者": actor.id, "行动类型": intent.action, "技能键": intent.skill_key, "目标ID": intent.target_id})
        if decision is not None:
            intent.cancelled = intent.cancelled or decision.cancelled
            intent.target_id = decision.target.id
        context.event("行动决策后", actor, decision.target if decision is not None else planned_target, f"{actor.name}确定行动", values={"行动者": actor.id, "行动类型": intent.action, "技能键": intent.skill_key, "目标ID": intent.target_id})
        actual_target = context.fighter_by_id(intent.target_id) or target
        if intent.cancelled or self._action_restricted(actor, "行动"):
            context.event("行动跳过后", actor, actor, f"{actor.name}未能行动", values={"行动者": actor.id, "行动类型": intent.action})
        elif intent.action == "技能":
            skill = self._skill_by_key(actor, intent.skill_key)
            uses_before = skill.uses if skill is not None else 0
            succeeded = self._cast_skill(context, actor, actual_target, skill)
            if skill is not None and skill.uses > uses_before:
                self._advance_skill_cursor(actor, skill)
            if not succeeded:
                self._basic_attack(context, actor, actual_target)
        else:
            self._basic_attack(context, actor, actual_target)
        context.action_intent = None
        self._advance_lifecycles(context, actor)
        context.event("行动结束", actor, actor, f"{actor.name}结束行动", values={"行动": context.action_number, "行动者": actor.id})

    def _decide_action(self, context, actor, default_target) -> ActionIntent:
        for rule in sorted(actor.tactic, key=lambda value: int(value.get("优先级", 0)), reverse=True):
            if not self._conditions_allow(context, actor, default_target, rule.get("条件") or (), 0, {}, ()):
                continue
            targets = self._select_targets(context, actor, default_target, rule.get("目标")) or [default_target]
            skills = self._select_skills(context, actor, rule.get("技能"))
            action = str(rule.get("行动") or ("技能" if skills else "普通攻击"))
            return ActionIntent(actor.id, action, targets[0].id, skills[0] if skills else "")
        skill = self._next_skill_from_cursor(actor)
        return ActionIntent(actor.id, "技能" if skill else "普通攻击", default_target.id, skill.key if skill else "")

    def _next_skill_from_cursor(self, actor: Fighter) -> Skill | None:
        if not actor.skills:
            return None
        start = actor.skill_cursor % len(actor.skills)
        for offset in range(len(actor.skills)):
            skill = actor.skills[(start + offset) % len(actor.skills)]
            if self._skill_available(actor, skill) and actor.spirit >= self._skill_spirit_cost(actor, skill):
                return skill
        return None

    @staticmethod
    def _advance_skill_cursor(actor: Fighter, skill: Skill) -> None:
        if not actor.skills:
            actor.skill_cursor = 0
            return
        index = next(
            (index for index, candidate in enumerate(actor.skills) if candidate.key == skill.key),
            None,
        )
        if index is not None:
            actor.skill_cursor = (index + 1) % len(actor.skills)

    def _build_fighter(self, snapshot: CombatantSnapshot) -> Fighter:
        attributes = self._normalize_attributes(snapshot.attributes)
        attributes["攻击"] = attributes.get("攻击", 0) + float(snapshot.weapon_attack)
        skills, passives = self._technique_rules(list(snapshot.techniques), attributes)
        attributes = self._normalize_attributes(attributes)
        health_max = max(1.0, attributes.get("血气上限", 1))
        spirit_max = max(0.0, attributes.get("精神上限", 0))
        return Fighter(
            id=str(snapshot.id), name=str(snapshot.name or "无名参战者"),
            attributes=attributes,
            health=self._clamp(health_max if snapshot.health is None else snapshot.health, 0, health_max),
            spirit=self._clamp(spirit_max if snapshot.spirit is None else snapshot.spirit, 0, spirit_max),
            shield=self._clamp(snapshot.shield, 0, max(0.0, attributes.get("护盾上限", 0))),
            statuses=[StatusState.from_dict(value) for value in snapshot.statuses],
            skills=list(skills), passives=list(passives),
            cooldowns={str(k): max(0, int(v)) for k, v in snapshot.cooldowns.items()},
            inventory={str(k): max(0, int(v)) for k, v in snapshot.inventory.items()},
            auto_medicine=snapshot.auto_medicine,
            medicine_threshold=self._clamp(snapshot.medicine_threshold, 0, 1),
            skill_cursor=max(0, int(snapshot.skill_cursor)), level=max(1, int(snapshot.level)),
            kind=str(snapshot.kind or "修士"), owner_id=str(snapshot.owner_id),
            controller_id=str(snapshot.controller_id or snapshot.id), form=str(snapshot.form or "本相"),
            forms=copy.deepcopy(dict(snapshot.forms)), tags=set(snapshot.tags), tactic=copy.deepcopy(list(snapshot.tactic)),
            battle_profile=self._normalize_battle_profile(snapshot.battle_profile),
        )

    @staticmethod
    def _fighter_result(fighter: Fighter) -> CombatantResult:
        return CombatantResult(
            id=fighter.id, name=fighter.name, attributes=dict(fighter.attributes),
            level=fighter.level, kind=fighter.kind,
            health=max(0.0, round(fighter.health, 3)), spirit=max(0.0, round(fighter.spirit, 3)),
            shield=max(0.0, round(fighter.shield, 3)),
            statuses=tuple(status for status in fighter.statuses if status.remaining_turns > 0 and status.duration_unit != "整场战斗"),
            cooldowns={k: v for k, v in fighter.cooldowns.items() if v > 0},
            inventory={k: v for k, v in fighter.inventory.items() if v > 0},
            consumed_items=dict(fighter.consumed_items), skill_cursor=fighter.skill_cursor,
            form=fighter.form, owner_id=fighter.owner_id, controller_id=fighter.controller_id,
            counts_for_victory=fighter.counts_for_victory,
        )

    def _next_action_order(self, context):
        while True:
            values = self._action_window(context)
            if values:
                return values

    def _action_window(self, context):
        ready = []
        for fighter in context.fighters:
            if not fighter.alive or not fighter.can_act:
                continue
            efficiency = self._action_efficiency(context, fighter)
            before = context.action_progress.get(fighter.id, 0)
            total = before + efficiency
            count = math.floor(total + 1e-9)
            context.action_progress[fighter.id] = min(max(total - count, 0), 1 - 1e-12)
            for ordinal in range(count):
                ready.append(((ordinal + 1 - before) / efficiency, -fighter.value("速度", 100), fighter.side, ordinal, fighter))
        ready.sort(key=lambda value: value[:4])
        return tuple(value[4] for value in ready)

    def _action_efficiency(self, context, fighter):
        rules = self.catalog.action_rules
        baseline = max(0.0001, float(rules.get("标准速度", 100)))
        minimum = max(0.0001, float(rules.get("最低有效速度", 25)))
        global_limit = max(1.000001, float(rules.get("最高行动效率", 2)))
        limit = max(1.000001, float(fighter.battle_profile.get("行动效率上限", global_limit)))
        effective = max(minimum, fighter.value("速度", 100))
        efficiency = limit * effective / (effective + (limit - 1) * baseline)

        response = dict(fighter.battle_profile.get("寡敌应变") or {})
        extra_enemies = max(0, len(context.enemies_of(fighter)) - 1)
        response_per_enemy = max(0.0, float(response.get("每名额外敌人行动效率", 0)))
        response_limit = max(0.0, float(response.get("行动效率增量上限", 0)))
        response_bonus = min(extra_enemies * response_per_enemy, response_limit)
        return min(limit, efficiency + response_bonus)

    @staticmethod
    def _normalize_battle_profile(value):
        profile = copy.deepcopy(dict(value or {}))
        allowed = {"行动效率上限", "寡敌应变", "同时承受控制上限", "控制持续上限"}
        unknown = set(profile) - allowed
        if unknown:
            raise ValueError("战斗规格存在未知字段：" + "、".join(sorted(str(item) for item in unknown)))
        if "行动效率上限" in profile:
            limit = profile["行动效率上限"]
            if isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit <= 1:
                raise ValueError("战斗规格.行动效率上限必须是大于 1 的数字")
        for field in ("同时承受控制上限", "控制持续上限"):
            if field in profile:
                limit = profile[field]
                if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                    raise ValueError(f"战斗规格.{field}必须是正整数")
        response = profile.get("寡敌应变")
        if response is not None:
            if not isinstance(response, Mapping):
                raise ValueError("战斗规格.寡敌应变必须是字典")
            response = dict(response)
            expected = {"每名额外敌人行动效率", "行动效率增量上限"}
            unknown = set(response) - expected
            if unknown:
                raise ValueError("战斗规格.寡敌应变存在未知字段：" + "、".join(sorted(str(item) for item in unknown)))
            for field in expected:
                number = response.get(field, 0)
                if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0:
                    raise ValueError(f"战斗规格.寡敌应变.{field}必须是非负数字")
            profile["寡敌应变"] = response
        return profile

    def _technique_rules(self, techniques, attributes):
        skills, passives = [], []
        for instance in sorted(techniques, key=lambda value: int(value.get("出生序号", 0))):
            for index, raw in enumerate(instance.get("能力") or ()):
                node = dict(raw)
                executor = self.catalog.parse_node(node).executor
                handler = self._assembly_handlers.get(executor)
                if handler is None:
                    raise ValueError(f"战斗核心未实现装配执行器：{executor}")
                handler(instance, index, node, attributes, skills, passives)
        skills.sort(key=self._skill_order_key)
        passives.sort(
            key=lambda value: (
                int(value.get("结算顺序", 1)),
                int(value.get("装配位序", 0)),
                str(value.get("物品编号") or ""),
                int(value.get("能力序号", 0)),
                int(value.get("效果序号", 0)),
            )
        )
        return tuple(skills), tuple(passives)

    @staticmethod
    def _assemble_attributes(instance, index, node, attributes, skills, passives):
        del index, skills, passives
        multiplier = float(instance.get("威力倍率", 1))
        for key, value in dict(node.get("属性") or {}).items():
            attributes[str(key)] = attributes.get(str(key), 0) + float(value) * multiplier

    @staticmethod
    def _assemble_active_skill(instance, index, node, attributes, skills, passives):
        del attributes, passives
        source_name = str(instance.get("功法") or instance.get("名称") or "能力")
        source_id = str(instance.get("编号") or source_name)
        skills.append(Skill(
            key=f"{instance.get('实例', source_name)}:{index}", name=str(node.get("名称") or source_name),
            born_order=int(instance.get("出生序号", 0)), release_order=int(node.get("释放顺序", index + 1)),
            source_id=source_id, ability_order=index,
            multiplier=float(instance.get("威力倍率", 1)), spirit_cost=max(0.0, float(node.get("精神消耗", 0))),
            cooldown_actions=max(0, int(node.get("冷却行动", 0))), effects=tuple(copy.deepcopy(node.get("效果") or ())),
            tags=tuple(str(value) for value in node.get("标签") or ()), costs=tuple(copy.deepcopy(node.get("额外代价") or ())),
            use_limit=max(0, int(node.get("使用次数", 0))), cooldown_group=str(node.get("共享冷却") or ""),
        ))

    @staticmethod
    def _assemble_passive_skill(instance, index, node, attributes, skills, passives):
        del attributes, skills
        source_name = str(instance.get("功法") or instance.get("名称") or "能力")
        source_id = str(instance.get("编号") or source_name)
        born_order = int(instance.get("出生序号", 0))
        for effect_index, raw in enumerate(node.get("效果") or ()):
            passives.append({
                "机制": f"{source_name}:{index}:{effect_index}",
                "结算顺序": int(node.get("结算顺序", 1)),
                "装配位序": born_order,
                "物品编号": source_id,
                "能力序号": index,
                "效果序号": effect_index,
                "节点": copy.deepcopy(dict(raw)),
            })

    def _normalize_attributes(self, values):
        result = {}
        for key, definition in self.catalog.attributes.items():
            value = float(values.get(key, definition.get("默认值", 0)))
            minimum = float(definition.get("最低值", -math.inf))
            maximum = float(definition.get("最高值", math.inf))
            unit = max(0.0, float(definition.get("最小单位", 0)))
            value = self._clamp(value, minimum, maximum)
            if unit:
                value = round(value / unit) * unit
            result[str(key)] = value
        return result

    def _recover_at_action_start(self, context, actor):
        for resource, attribute in dict(self.catalog.action_rules.get("行动开始恢复") or {}).items():
            amount = actor.value(str(attribute), 0)
            if amount > 0:
                self._mechanism_recover_resource(context, actor, actor, {"目标": {"能力": "选择目标", "范围": "自身"}, "资源": resource, "数值": amount, "标签": ["自然恢复"]}, 1)

    def _tick_cooldowns(self, context, fighter):
        for key in tuple(fighter.cooldowns):
            before = fighter.cooldowns[key]
            after = max(0, before - 1)
            fighter.cooldowns[key] = after
            skill = self._skill_by_key(fighter, key)
            context.event("技能冷却变化后", fighter, fighter, f"{skill.name if skill else key}冷却推进", after - before, values={"技能": skill.name if skill else key, "技能键": key, "变化前数值": before, "变化后数值": after})
            if before > 0 and after == 0:
                context.event("技能冷却完成后", fighter, fighter, f"{skill.name if skill else key}冷却完成", values={"技能": skill.name if skill else key, "技能键": key})

    def _skill_spirit_cost(self, actor, skill):
        return max(0.0, skill.spirit_cost * max(0.0, 1 - self._percent(actor, "精神消耗修正")))

    def _cast_skill(self, context, actor, target, skill, *, triggered=False, ignore_cost=False, ignore_cooldown=False, multiplier=1.0):
        if skill is None or skill.disabled or (skill.use_limit and skill.uses >= skill.use_limit):
            return False
        if self._action_restricted(actor, "技能"):
            context.event(
                "技能施放失败后",
                actor,
                target,
                f"{skill.name}受禁制无法施展",
                values={"技能": skill.name, "技能键": skill.key, "原因": "行动限制"},
            )
            return False
        if not ignore_cooldown and actor.cooldowns.get(skill.key, 0) > 0:
            return False
        spirit_cost = self._skill_spirit_cost(actor, skill)
        if not ignore_cost and actor.spirit < spirit_cost:
            context.event("技能施放失败后", actor, target, f"{skill.name}精神不足", values={"技能": skill.name, "技能键": skill.key, "原因": "精神不足"})
            return False
        frame = self._dispatch_event(context, kind="技能施放前", source=actor, target=target, values={"技能": skill.name, "技能键": skill.key, "精神消耗": spirit_cost, "行动类型": "触发技能" if triggered else "技能"}, tags=skill.tags)
        if frame.cancelled:
            self._dispatch_event(context, kind="技能施放失败后", source=actor, target=target, values={"技能": skill.name, "技能键": skill.key, "原因": "被取消"}, tags=skill.tags)
            return False
        target = frame.target
        snapshot = self._transaction_snapshot(context)
        if not ignore_cost:
            if spirit_cost > 0 and not self._mechanism_consume_resource(
                context,
                actor,
                actor,
                {
                    "目标": {"能力": "选择目标", "范围": "自身"},
                    "资源": "精神",
                    "数值": spirit_cost,
                    "不足时是否失败": True,
                },
                1,
            ):
                self._restore_transaction(context, snapshot)
                return False
            for cost in skill.costs:
                if not self._execute_mechanism(context, actor, target, dict(cost), skill.multiplier):
                    self._restore_transaction(context, snapshot)
                    self._dispatch_event(context, kind="技能施放失败后", source=actor, target=target, values={"技能": skill.name, "技能键": skill.key, "原因": "额外代价不足"}, tags=skill.tags)
                    return False
        actor.current_skill = skill.key
        success = True
        try:
            for node in skill.effects:
                success = self._execute_mechanism(context, actor, target, dict(node), skill.multiplier * multiplier) and success
        finally:
            actor.current_skill = ""
        reduction = self._clamp(self._percent(actor, "冷却缩减"), -5, 0.8)
        cooldown = max(0, math.ceil(skill.cooldown_actions * (1 - reduction)))
        if not ignore_cooldown and cooldown:
            actor.cooldowns[skill.key] = cooldown
            if skill.cooldown_group:
                for other in actor.skills:
                    if other.cooldown_group == skill.cooldown_group:
                        actor.cooldowns[other.key] = max(actor.cooldowns.get(other.key, 0), cooldown)
        skill.uses += 1
        self._dispatch_event(context, kind="技能施放后", source=actor, target=target, values={"技能": skill.name, "技能键": skill.key, "精神消耗": spirit_cost, "行动类型": "触发技能" if triggered else "技能"}, tags=skill.tags)
        return success

    def _basic_attack(self, context, source, target):
        if self._action_restricted(source, "普通攻击"):
            return False
        frame = self._dispatch_event(context, kind="普通攻击前", source=source, target=target, values={"行动类型": "普通攻击"}, tags=("普通攻击",))
        if frame.cancelled:
            return False
        target = frame.target
        power = max(0.0, 1 + self._percent(source, "普通攻击威力"))
        applied = self._deal_attack(context, source, target, power, "普通攻击", tags=("普通攻击",))
        self._dispatch_event(context, kind="普通攻击后", source=source, target=target, amount=applied, values={"实际数值": applied, "行动类型": "普通攻击"}, tags=("普通攻击",))
        return True

    @staticmethod
    def _action_restricted(fighter, action):
        return any("行动" in status.action_limits or action in status.action_limits for status in fighter.statuses)

    def _deal_attack(self, context, source, target, power, label, *, damage_form="直接", defense_rule="普通", tags=(), can_miss=True, can_critical=True, can_block=True, allow_followups=True, raw_amount=None, can_lifesteal=True):
        raw = max(0.0, float(raw_amount) if raw_amount is not None else source.value("攻击", 1) * max(0.0, float(power)))
        resolution = self._apply_damage(context, source, target, raw, label=label, damage_form=damage_form, defense_rule=defense_rule, can_miss=can_miss, can_critical=can_critical, can_block=can_block, tags=tuple(tags))
        if can_lifesteal and resolution.health_damage > 0 and source.alive:
            rate = self._percent(source, "吸血率")
            if rate > 0:
                self._mechanism_recover_resource(context, source, source, {"目标": {"能力": "选择目标", "范围": "自身"}, "资源": "血气", "数值": resolution.health_damage * rate}, 1)
        if allow_followups and resolution.actual_damage > 0 and target.alive and self._judgement(context, "连击", self._percent(source, "连击率")):
            self._deal_attack(context, source, target, power * self._percent(source, "连击伤害", 1), "连击", tags=tuple((*tags, "连击", "派生伤害")), allow_followups=False)
        return resolution.actual_damage

    def _apply_damage(self, context, source, target, amount, *, ignore_defense=False, label="伤害", damage_form="直接", defense_rule="普通", can_miss=False, can_critical=True, can_block=True, tags=(), allow_reactions=True):
        effective_rule = "无视防御" if ignore_defense and defense_rule == "普通" else defense_rule
        judgement = self._dispatch_event(context, kind="命中判定前", source=source, target=target, amount=amount, values={"行动类型": damage_form}, tags=tags)
        tags = tuple(judgement.tags)
        allow_critical = can_critical
        if allow_critical:
            judgement = self._dispatch_event(context, kind="暴击判定前", source=source, target=target, amount=amount, values={"暴击率": self._percent(source, "暴击率"), "行动类型": damage_form}, tags=tags)
            tags = tuple(judgement.tags)
            allow_critical = not judgement.cancelled
        if can_block and effective_rule != "真实":
            judgement = self._dispatch_event(context, kind="格挡判定前", source=source, target=target, amount=amount, values={"格挡率": self._percent(target, "格挡率"), "行动类型": damage_form}, tags=tags)
            tags = tuple(judgement.tags)
        resolution = self.damage.resolve(
            DamageRequest(amount=max(0.0, float(amount)), label=label, damage_form=damage_form, defense_rule=effective_rule, tags=tags, can_miss=can_miss, can_critical=allow_critical, can_block=can_block),
            source=source, target=target, rng=context.rng,
            judge=lambda kind, chance, roll: self._judgement(context, kind, chance, roll),
        )
        if not resolution.hit:
            self._dispatch_event(context, kind="闪避后", source=source, target=target, values=resolution.values(), tags=tags)
            return resolution
        self._dispatch_event(context, kind="命中后", source=source, target=target, amount=resolution.breakdown.limited, values=resolution.values(), tags=tags)
        pre = self._dispatch_event(context, kind="造成伤害前", source=source, target=target, amount=resolution.breakdown.limited, values={**resolution.values(), "当前数值": resolution.breakdown.limited}, tags=tags)
        tags = tuple(pre.tags)
        if pre.target is not target:
            target = pre.target
            resolution = self.damage.resolve(resolution.request, source=source, target=target, rng=context.rng, judge=lambda kind, chance, roll: self._judgement(context, kind, chance, roll))
        if "伤害" in self._immunities(target):
            pre.cancelled = True
        target_was_alive = target.alive
        resolution = self.damage.with_limited_damage(resolution, 0 if pre.cancelled else pre.amount)
        if resolution.defeated:
            fatal = self._dispatch_event(context, kind="受到致命伤害", source=source, target=target, amount=resolution.actual_damage, values=resolution.values(), tags=tags)
            if fatal.cancelled:
                resolution = self.damage.with_minimum_health(resolution, float(fatal.facts.get("保留血气", 1)))
        target.shield = resolution.shield_after
        target.health = resolution.health_after
        values = resolution.values()
        values["实际数值"] = resolution.actual_damage
        if resolution.critical:
            self._dispatch_event(context, kind="暴击后", source=source, target=target, amount=resolution.actual_damage, values=values, tags=tags)
        if resolution.blocked:
            self._dispatch_event(context, kind="格挡后", source=source, target=target, amount=resolution.actual_damage, values=values, tags=tags)
        if resolution.shield_damage > 0:
            self._dispatch_event(context, kind="护盾吸收后", source=source, target=target, amount=resolution.shield_damage, values=values, tags=tags)
        self._dispatch_event(context, kind="造成伤害后", source=source, target=target, amount=resolution.actual_damage, values=values, tags=tags)
        self._dispatch_event(context, kind="受到伤害后", source=source, target=target, amount=resolution.actual_damage, values=values, tags=tags)
        if resolution.shield_broken:
            self._dispatch_event(context, kind="护盾破碎后", source=source, target=target, amount=resolution.shield_damage, values=values, tags=tags)
        if target_was_alive and not target.alive:
            self._dispatch_event(context, kind="死亡后", source=source, target=target, amount=resolution.actual_damage, values=values, tags=tags)
            if target.kind == "构造物" or target.summoned:
                self._retire_battle_object(
                    context,
                    source,
                    target,
                    "构造物" if target.kind == "构造物" else "参战者",
                )
            else:
                self._remove_source_lifetimes(context, target)
            if not target.alive:
                self._dispatch_event(context, kind="击杀后", source=source, target=target, amount=resolution.actual_damage, values=values, tags=tags)
        if allow_reactions and resolution.actual_damage > 0 and damage_form == "直接" and source is not target:
            reflect = resolution.actual_damage * self._percent(target, "反伤率")
            if reflect > 0 and source.alive:
                self._apply_damage(context, target, source, reflect, label="反伤", damage_form="反伤", defense_rule="真实", can_critical=False, can_block=False, tags=("反伤", "派生伤害"), allow_reactions=False)
            if source.alive and target.alive and self._judgement(context, "反击", self._percent(target, "反击率")):
                self._deal_attack(context, target, source, 1, "反击", tags=("反击", "派生伤害"), allow_followups=False)
        return resolution

    def _advance_lifecycles(self, context, actor):
        kept = []
        for status in actor.statuses:
            if status.duration_unit == "状态承受者行动":
                status.remaining_turns -= 1
            if status.remaining_turns > 0 or status.duration_unit == "整场战斗":
                kept.append(status)
            else:
                context.event("移除状态后", actor, actor, f"{status.name}消散", values={"状态": status.name, "原因": "到期"}, tags=status.tags)
        actor.statuses = kept
        for obj in list(context.combat_objects.values()):
            if obj.remaining_actions > 0:
                obj.remaining_actions -= 1
                if obj.remaining_actions == 0:
                    context.combat_objects.pop(obj.id, None)
                    shell = context.fighter_by_id(obj.id)
                    if shell is not None:
                        shell.active = False
                        shell.health = 0
                    context.event("战斗对象退场后", actor, shell or actor, f"{obj.name}消散", values={"对象ID": obj.id, "对象类型": obj.kind})

    def _use_medicine(self, context, fighter):
        if not fighter.auto_medicine:
            return
        for effect_type, resource in (("恢复血气", "血气"), ("恢复精神", "精神")):
            current, maximum = self._resource_values(fighter, resource)
            if maximum <= 0 or current / maximum >= fighter.medicine_threshold:
                continue
            candidates = []
            for item_id, quantity in fighter.inventory.items():
                use = (context.item_definitions.get(item_id) or {}).get("使用效果") or {}
                if quantity > 0 and use.get("类型") == effect_type:
                    candidates.append((float(use.get("恢复量", 0)), item_id))
            if not candidates:
                continue
            amount, item_id = min(candidates)
            fighter.inventory[item_id] -= 1
            fighter.consumed_items[item_id] = fighter.consumed_items.get(item_id, 0) + 1
            self._mechanism_recover_resource(context, fighter, fighter, {"目标": {"能力": "选择目标", "范围": "自身"}, "资源": resource, "数值": amount}, 1)

    @staticmethod
    def _percent(target, attribute, default=0.0):
        if attribute not in target.attributes and not any(attribute in status.modifiers for status in target.statuses):
            return float(default)
        return target.value(attribute, default * 100) / 100.0


__all__ = ["BattleEngine"]
