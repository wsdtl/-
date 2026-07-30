"""由中文 JSON 机制驱动的轻量自动战斗编排。"""

from __future__ import annotations

from collections.abc import Mapping
import math
import random
from typing import Any, Callable

from .battle.damage import DamageEngine, DamageRequest, DamageResolution
from .battle.mechanics import MechanismRuntime
from .battle.models import (
    BattleContext as _BattleContext,
    BattleEvent,
    BattleOutcome,
    CombatCatalog,
    CombatantResult,
    CombatantSnapshot,
    Fighter as _Fighter,
    Skill as _Skill,
    StatusState,
)


class BattleEngine(MechanismRuntime):
    """执行双方面自动战斗；玩法层负责选择敌人与保存轮次。"""

    def __init__(self, combat_rules: Mapping[str, Any] | None = None) -> None:
        self.catalog = CombatCatalog.from_mapping(combat_rules)
        self.damage = DamageEngine(self.catalog.damage_rules)
        self._mechanism_handlers: dict[str, Callable[..., None]] = {
            "顺序执行": self._mechanism_sequence,
            "条件执行": self._mechanism_conditional,
            "随机执行": self._mechanism_random,
            "监听事件": self._mechanism_listener,
            "引用机制": self._mechanism_reference,
            "造成伤害": self._mechanism_damage,
            "恢复资源": self._mechanism_recover_resource,
            "消耗资源": self._mechanism_consume_resource,
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
            "修改蓄势进度": self._mechanism_modify_charge,
            "追加行动": self._mechanism_additional_action,
            "分摊伤害": self._mechanism_share_damage,
            "转移伤害": self._mechanism_transfer_damage,
            "抵挡致命伤害": self._mechanism_fatal_guard,
            "复活": self._mechanism_revive,
        }
        self._condition_handlers: dict[str, Callable[..., bool]] = {
            "概率条件": self._condition_probability,
            "数值条件": self._condition_numeric,
            "状态条件": self._condition_status,
            "类型条件": self._condition_type,
            "组合条件": self._condition_combined,
            "标签条件": self._condition_tags,
        }
        self._value_handlers: dict[str, Callable[..., float]] = {
            "读取数值": self._value_read,
            "计算数值": self._value_calculate,
            "随机数值": self._value_random,
        }
        self._target_handlers: dict[str, Callable[..., _Fighter]] = {
            "选择目标": self._target_select,
        }
        self._skill_selector_handlers: dict[str, Callable[..., list[str]]] = {
            "选择技能": self._skills_select,
        }
        self._assembly_handlers: dict[str, Callable[..., None]] = {
            "装配属性": self._assemble_attributes,
            "装配主动技能": self._assemble_active_skill,
            "装配被动技能": self._assemble_passive_skill,
        }

    def simulate(
        self,
        *,
        left: CombatantSnapshot,
        right: CombatantSnapshot,
        item_definitions: dict[str, dict[str, Any]],
        seed: int,
        action_limit: int,
    ) -> BattleOutcome:
        return self.simulate_teams(
            left=(left,),
            right=(right,),
            item_definitions=item_definitions,
            seed=seed,
            action_limit=action_limit,
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
        snapshots = left + right
        ids = [str(value.id).strip() for value in snapshots]
        if any(not value for value in ids):
            raise ValueError("参战者 ID 不能为空")
        if len(ids) != len(set(ids)):
            raise ValueError("参战者不能使用重复 ID")
        left_fighters = tuple(self._build_fighter(value) for value in left)
        right_fighters = tuple(self._build_fighter(value) for value in right)
        if share_left_inventory:
            shared_inventory = left_fighters[0].inventory
            for fighter in left_fighters[1:]:
                fighter.inventory = shared_inventory
        left_fighter = left_fighters[0]
        right_fighter = right_fighters[0]
        context = _BattleContext(
            rng=random.Random(int(seed)),
            left=left_fighter,
            right=right_fighter,
            item_definitions=item_definitions,
            left_team=left_fighters,
            right_team=right_fighters,
        )
        context.engine = self
        context.action_progress = {fighter.id: 0.0 for fighter in context.fighters}
        left_names = "、".join(value.name for value in left_fighters)
        right_names = "、".join(value.name for value in right_fighters)
        context.event(
            "战斗开始",
            left_fighter,
            right_fighter,
            f"{left_names}与{right_names}进入战斗",
            values={"左方": left_names, "右方": right_names},
        )

        opening_round = True
        while context.both_sides_alive and context.action_number < max(1, int(action_limit)):
            order = (
                self._opening_order(context)
                if opening_round
                else self._next_action_order(context)
            )
            opening_round = False
            for actor in order:
                if not context.both_sides_alive:
                    break
                if not actor.alive:
                    continue
                target = context.opponent_of(actor)
                context.action_number += 1
                context.trigger_counts.clear()
                context.additional_action_counts.clear()
                context.event(
                    "行动开始",
                    actor,
                    actor,
                    f"{actor.name}开始行动",
                    values={"行动": context.action_number},
                )
                self._trigger_statuses(context, actor)
                if actor.alive:
                    if not self._action_restricted(actor, "使用丹药"):
                        self._use_medicine(context, actor)
                    self._tick_cooldowns(actor)
                    if self._action_restricted(actor, "行动"):
                        context.event(
                            "action_restricted",
                            actor,
                            actor,
                            f"{actor.name}无法行动",
                            values={"行动类型": "行动"},
                            dispatch=False,
                        )
                    elif not self._use_skill(context, actor, target):
                        self._basic_attack(context, actor, target)
                self._advance_statuses(context, actor)
                context.event(
                    "行动结束",
                    actor,
                    actor,
                    f"{actor.name}结束行动",
                    values={"行动": context.action_number},
                )
                if context.action_number >= max(1, int(action_limit)):
                    break

        left_alive = tuple(value for value in left_fighters if value.alive)
        right_alive = tuple(value for value in right_fighters if value.alive)
        draw = bool(left_alive) == bool(right_alive)
        winners = () if draw else left_alive or right_alive
        winner_names = "、".join(value.name for value in winners)
        context.event(
            "战斗结束",
            left_fighter,
            right_fighter,
            "战斗未分胜负" if draw else f"{winner_names}取胜",
            values={
                "结果": "未分胜负" if draw else "分出胜负",
                "胜者": "" if draw else winner_names,
                "行动数": context.action_number,
            },
        )
        left_results = tuple(self._fighter_result(value) for value in left_fighters)
        right_results = tuple(self._fighter_result(value) for value in right_fighters)
        return BattleOutcome(
            left=left_results[0],
            right=right_results[0],
            actions=context.action_number,
            events=tuple(context.events),
            trigger_activations=sum(context.battle_trigger_counts.values()),
            left_team=left_results,
            right_team=right_results,
        )

    def _build_fighter(self, snapshot: CombatantSnapshot) -> _Fighter:
        attributes = self._normalize_attributes(snapshot.attributes)
        attributes["攻击"] = attributes.get("攻击", 0.0) + float(snapshot.weapon_attack)
        skills, passives = self._technique_rules(list(snapshot.techniques), attributes)
        attributes = self._normalize_attributes(attributes)
        health_max = max(1.0, attributes.get("血气上限", 1.0))
        spirit_max = max(0.0, attributes.get("精神上限", 0.0))
        health = health_max if snapshot.health is None else float(snapshot.health)
        spirit = spirit_max if snapshot.spirit is None else float(snapshot.spirit)
        return _Fighter(
            id=str(snapshot.id),
            name=str(snapshot.name or "无名参战者"),
            attributes=attributes,
            level=max(1, int(snapshot.level)),
            kind=str(snapshot.kind or "参战者"),
            health=min(health_max, max(0.0, health)),
            spirit=min(spirit_max, max(0.0, spirit)),
            shield=min(
                max(0.0, attributes.get("护盾上限", 0.0)),
                max(0.0, float(snapshot.shield)),
            ),
            statuses=[StatusState.from_dict(dict(value)) for value in snapshot.statuses],
            skills=skills,
            passives=passives,
            cooldowns={
                str(key): max(0, int(value))
                for key, value in dict(snapshot.cooldowns).items()
            },
            inventory={
                str(key): max(0, int(value))
                for key, value in dict(snapshot.inventory).items()
            },
            auto_medicine=bool(snapshot.auto_medicine),
            medicine_threshold=max(0.0, min(1.0, float(snapshot.medicine_threshold))),
            skill_cursor=max(0, int(snapshot.skill_cursor)),
            charge_progress={
                str(key): max(0, int(value))
                for key, value in dict(snapshot.charge_progress).items()
            },
            charging_skill=str(snapshot.charging_skill or ""),
        )

    @staticmethod
    def _fighter_result(fighter: _Fighter) -> CombatantResult:
        return CombatantResult(
            id=fighter.id,
            name=fighter.name,
            attributes=dict(fighter.attributes),
            level=fighter.level,
            kind=fighter.kind,
            health=max(0.0, round(fighter.health, 3)),
            spirit=max(0.0, round(fighter.spirit, 3)),
            shield=max(0.0, round(fighter.shield, 3)),
            statuses=tuple(
                status
                for status in fighter.statuses
                if status.remaining_turns > 0 and status.duration_unit != "整场战斗"
            ),
            cooldowns={
                key: value for key, value in fighter.cooldowns.items() if value > 0
            },
            inventory={key: value for key, value in fighter.inventory.items() if value > 0},
            consumed_items=dict(fighter.consumed_items),
            skill_cursor=fighter.skill_cursor,
            charge_progress={
                key: value for key, value in fighter.charge_progress.items() if value > 0
            },
            charging_skill=fighter.charging_skill,
        )

    @staticmethod
    def _opening_order(context: _BattleContext) -> tuple[_Fighter, ...]:
        return tuple(
            sorted(
                context.fighters,
                key=lambda fighter: (
                    -fighter.value("速度", 100.0),
                    context.side_index(fighter),
                ),
            )
        )

    def _next_action_order(self, context: _BattleContext) -> tuple[_Fighter, ...]:
        while True:
            order = self._action_window(context)
            if order:
                return order

    def _action_window(self, context: _BattleContext) -> tuple[_Fighter, ...]:
        occurrences: list[tuple[float, float, int, int, _Fighter]] = []
        for fighter in context.fighters:
            if not fighter.alive:
                continue
            speed = fighter.value("速度", 100.0)
            efficiency = self._action_efficiency(speed)
            before = context.action_progress.get(fighter.id, 0.0)
            total = before + efficiency
            action_count = math.floor(total + 1e-9)
            context.action_progress[fighter.id] = min(
                max(total - action_count, 0.0),
                1.0 - 1e-12,
            )
            for ordinal in range(action_count):
                ready_at = (ordinal + 1.0 - before) / efficiency
                occurrences.append(
                    (
                        ready_at,
                        -speed,
                        context.side_index(fighter),
                        ordinal,
                        fighter,
                    )
                )
        occurrences.sort(key=lambda value: value[:4])
        return tuple(value[4] for value in occurrences)

    def _action_efficiency(self, speed: float) -> float:
        rules = self.catalog.action_rules
        baseline = max(0.0001, float(rules.get("标准速度", 100)))
        minimum = max(0.0001, float(rules.get("最低有效速度", 25)))
        limit = max(1.000001, float(rules.get("最高行动效率", 2)))
        effective = max(minimum, float(speed))
        return limit * effective / (effective + (limit - 1.0) * baseline)

    def _technique_rules(
        self,
        techniques: list[dict[str, Any]],
        attributes: dict[str, float],
    ) -> tuple[tuple[_Skill, ...], tuple[dict[str, Any], ...]]:
        skills: list[_Skill] = []
        passives: list[dict[str, Any]] = []
        for instance in sorted(techniques, key=lambda value: int(value.get("出生序号") or 0)):
            for affix in instance.get("词条") or ():
                key = str(affix.get("属性") or "")
                if key:
                    attributes[key] = attributes.get(key, 0.0) + float(affix.get("数值") or 0)
            for index, raw_node in enumerate(instance.get("能力") or ()):
                node = dict(raw_node)
                executor = self.catalog.parse_node(node).executor
                handler = self._assembly_handlers.get(executor)
                if handler is None:
                    raise ValueError(f"战斗核心未实现装配执行器：{executor or '<空>'}")
                handler(instance, index, node, attributes, skills, passives)
        skills.sort(key=lambda value: value.release_order)
        passives.sort(key=lambda value: int(value["结算顺序"]))
        return tuple(skills), tuple(passives)

    @staticmethod
    def _assemble_attributes(instance, index, node, attributes, skills, passives) -> None:
        del index, skills, passives
        multiplier = float(instance.get("威力倍率") or 1.0)
        for key, amount in dict(node.get("属性") or {}).items():
            attributes[str(key)] = attributes.get(str(key), 0.0) + float(amount) * multiplier

    @staticmethod
    def _assemble_active_skill(instance, index, node, attributes, skills, passives) -> None:
        del attributes, passives
        source_name = str(instance.get("功法") or instance.get("名称") or "能力")
        skills.append(
            _Skill(
                key=f"{instance['实例']}:{source_name}:{index}",
                name=str(node.get("名称") or source_name),
                born_order=int(instance.get("出生序号") or 0),
                release_order=int(node["释放顺序"]),
                multiplier=float(instance.get("威力倍率") or 1.0),
                spirit_cost=max(0.0, float(node.get("精神消耗") or 0)),
                cooldown_turns=max(0, int(node.get("冷却回合") or 0)),
                charge_turns=max(0, int(node.get("蓄势回合") or 0)),
                effects=tuple(dict(value) for value in node.get("效果") or ()),
            )
        )

    def _assemble_passive_skill(self, instance, index, node, attributes, skills, passives) -> None:
        del index, attributes, skills
        source_name = str(instance.get("功法") or instance.get("名称") or "能力")
        for effect_index, raw_effect in enumerate(node.get("效果") or ()):
            effect = dict(raw_effect)
            parsed = self.catalog.parse_node(effect)
            if parsed.executor == "引用机制":
                mechanism_id = str(effect.get("机制") or "")
                definition = dict(self.catalog.require_mechanism(mechanism_id))
            else:
                mechanism_id = f"{source_name}:{node.get('名称') or '被动'}:{effect_index + 1}"
                definition = effect
            passives.append(
                {
                    "机制": mechanism_id,
                    "节点": definition,
                    "实例": str(instance["实例"]),
                    "来源": source_name,
                    "结算顺序": int(node["结算顺序"]),
                    "威力倍率": float(instance.get("威力倍率") or 1.0),
                }
            )

    def _normalize_attributes(self, values: Mapping[str, Any]) -> dict[str, float]:
        """按 JSON 的边界裁定最终面板；未知属性不静默进入战斗。"""

        result: dict[str, float] = {}
        for key, definition in self.catalog.attributes.items():
            raw = values.get(key, definition.get("默认值", 0.0))
            try:
                amount = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"战斗属性不是数字：{key}={raw!r}") from exc
            minimum = float(definition.get("最低值", amount))
            maximum = float(definition.get("最高值", amount))
            result[str(key)] = min(maximum, max(minimum, amount))
        unknown = set(values) - set(self.catalog.attributes)
        if unknown and self.catalog.attributes:
            raise ValueError("战斗输入包含未登记属性：" + ", ".join(sorted(str(key) for key in unknown)))
        return result

    def _trigger_statuses(self, context: _BattleContext, actor: _Fighter) -> None:
        for status in actor.statuses:
            damage = (
                status.flat_damage + status.source_attack * status.damage_attack_ratio
            ) * max(1, status.stacks)
            if damage > 0 and actor.alive:
                source = context.fighter_by_id(status.source)
                if source is None:
                    source = _Fighter(
                        status.source or "departed",
                        status.source_name or "未知来源",
                        {"攻击": status.source_attack},
                        1.0,
                        0.0,
                    )
                previous = context.current_mechanism
                context.current_mechanism = status.source_mechanism or status.name
                try:
                    self._apply_damage(
                        context,
                        source,
                        actor,
                        damage,
                        ignore_defense=status.defense_rule in {"无视防御", "真实"},
                        label=status.name,
                        damage_form=status.damage_form,
                        defense_rule=status.defense_rule,
                        can_critical=status.can_critical,
                        can_block=status.can_block,
                        tags=status.tags,
                    )
                finally:
                    context.current_mechanism = previous

    @staticmethod
    def _advance_statuses(context: _BattleContext, actor: _Fighter) -> None:
        kept: list[StatusState] = []
        for status in actor.statuses:
            if status.duration_unit == "状态承受者行动":
                status.remaining_turns -= 1
            if status.remaining_turns > 0:
                kept.append(status)
            else:
                context.event("status_end", actor, actor, f"{status.name}消散", dispatch=False)
        actor.statuses = kept

    @staticmethod
    def _tick_cooldowns(fighter: _Fighter) -> None:
        for key in tuple(fighter.cooldowns):
            fighter.cooldowns[key] = max(0, fighter.cooldowns[key] - 1)

    def _use_skill(
        self,
        context: _BattleContext,
        actor: _Fighter,
        target: _Fighter,
    ) -> bool:
        if not actor.skills or self._action_restricted(actor, "技能"):
            return False

        if actor.charging_skill:
            charging = next(
                (skill for skill in actor.skills if skill.key == actor.charging_skill),
                None,
            )
            if charging is None or charging.charge_turns <= 0:
                actor.charging_skill = ""
            elif actor.charge_progress.get(charging.key, 0) < charging.charge_turns:
                self._advance_charge(context, actor, target, charging)
                return True
            elif actor.cooldowns.get(charging.key, 0) <= 0:
                spirit_cost = self._skill_spirit_cost(actor, charging)
                if actor.spirit >= spirit_cost:
                    self._cast_skill(context, actor, target, charging, spirit_cost)
                    return True
                context.event(
                    "charge_wait",
                    actor,
                    actor,
                    f"{charging.name}蓄势已成，精神不足",
                    values={"技能": charging.name, "所需精神": spirit_cost},
                    dispatch=False,
                )
                return True
            else:
                return True

        for skill in actor.skills:
            if actor.cooldowns.get(skill.key, 0) > 0:
                continue
            spirit_cost = self._skill_spirit_cost(actor, skill)
            if actor.spirit < spirit_cost:
                continue
            if skill.charge_turns > 0:
                actor.charging_skill = skill.key
                self._advance_charge(context, actor, target, skill)
                return True
            self._cast_skill(context, actor, target, skill, spirit_cost)
            return True
        return False

    def _skill_spirit_cost(self, actor: _Fighter, skill: _Skill) -> float:
        cost_rate = 1.0 - self._percent(actor, "精神消耗修正")
        return max(0.0, skill.spirit_cost * max(0.0, cost_rate))

    def _advance_charge(
        self,
        context: _BattleContext,
        actor: _Fighter,
        target: _Fighter,
        skill: _Skill,
    ) -> None:
        before = actor.charge_progress.get(skill.key, 0)
        after = min(skill.charge_turns, before + 1)
        actor.charge_progress[skill.key] = after
        values = {
            "技能": skill.name,
            "技能键": skill.key,
            "原蓄势进度": before,
            "蓄势进度": after,
            "蓄势上限": skill.charge_turns,
        }
        context.event(
            "蓄势后",
            actor,
            target,
            f"{actor.name}为{skill.name}蓄势（{after}/{skill.charge_turns}）",
            after,
            values=values,
        )
        current = actor.charge_progress.get(skill.key, 0)
        if current >= skill.charge_turns:
            values["蓄势进度"] = current
            context.event(
                "蓄势完成后",
                actor,
                target,
                f"{skill.name}蓄势完成",
                current,
                values=values,
            )

    def _cast_skill(
        self,
        context: _BattleContext,
        actor: _Fighter,
        target: _Fighter,
        skill: _Skill,
        spirit_cost: float,
    ) -> None:
        actor.skill_cursor = 0
        actor.spirit -= spirit_cost
        context.event(
            "skill",
            actor,
            target,
            f"施展{skill.name}，消耗{_number(spirit_cost)}点精神",
            spirit_cost,
            values={"技能": skill.name, "资源消耗": spirit_cost},
            dispatch=False,
        )
        actor.current_skill = skill.key
        try:
            for effect in skill.effects:
                self._execute_mechanism(
                    context,
                    actor,
                    target,
                    dict(effect),
                    skill.multiplier,
                    event_amount=0.0,
                    event_values={},
                )
            reduction = min(0.8, max(-5.0, self._percent(actor, "冷却缩减")))
            cooldown = max(0, math.ceil(skill.cooldown_turns * (1.0 - reduction)))
            if cooldown:
                actor.cooldowns[skill.key] = cooldown
            context.event(
                "技能施放后",
                actor,
                target,
                f"{skill.name}施放完成",
                values={"技能": skill.name, "技能键": skill.key},
            )
        finally:
            actor.current_skill = ""
            actor.charge_progress.pop(skill.key, None)
            if actor.charging_skill == skill.key:
                actor.charging_skill = ""

    def _basic_attack(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
    ) -> float:
        if self._action_restricted(source, "普通攻击"):
            context.event(
                "action_restricted",
                source,
                source,
                f"{source.name}无法普通攻击",
                values={"行动类型": "普通攻击"},
                dispatch=False,
            )
            return 0.0
        power = 1.0 + self._percent(source, "普通攻击威力")
        applied = self._deal_attack(
            context,
            source,
            target,
            max(0.0, power),
            "基础攻击",
            damage_form="直接",
            tags=("普通攻击",),
        )
        context.event(
            "普通攻击后",
            source,
            target,
            f"{source.name}完成普通攻击",
            applied,
            values={"实际伤害": applied},
            tags=("普通攻击",),
        )
        return applied

    @staticmethod
    def _action_restricted(fighter: _Fighter, action: str) -> bool:
        return any(
            "行动" in status.action_limits or action in status.action_limits
            for status in fighter.statuses
        )

    def _deal_attack(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        power: float,
        label: str,
        *,
        damage_form: str = "直接",
        defense_rule: str = "普通",
        tags: tuple[str, ...] = (),
        can_miss: bool = True,
        can_critical: bool = True,
        can_block: bool = True,
        allow_followups: bool = True,
        raw_amount: float | None = None,
        can_lifesteal: bool = True,
    ) -> float:
        raw = max(
            0.0,
            float(raw_amount)
            if raw_amount is not None
            else source.value("攻击", 1.0) * max(0.0, float(power)),
        )
        resolution = self._apply_damage(
            context,
            source,
            target,
            raw,
            label=label,
            damage_form=damage_form,
            defense_rule=defense_rule,
            can_miss=can_miss,
            can_critical=can_critical,
            can_block=can_block,
            tags=tags,
        )
        applied = resolution.actual_damage
        lifesteal = self._percent(source, "吸血率")
        if can_lifesteal and resolution.health_damage > 0 and lifesteal > 0 and source.alive:
            amount = min(
                source.health_max - source.health,
                resolution.health_damage * lifesteal,
            )
            if amount > 0:
                source.health += amount
                context.event("heal", source, source, "血气回流", amount)
        if (
            allow_followups
            and applied > 0
            and target.alive
            and context.rng.random() < self._percent(source, "连击率")
        ):
            combo_power = max(0.0, power * self._percent(source, "连击伤害", 1.0))
            self._deal_attack(
                context,
                source,
                target,
                combo_power,
                "连击",
                damage_form="直接",
                defense_rule=defense_rule,
                tags=tuple((*tags, "连击", "派生伤害")),
                allow_followups=False,
            )
        return applied

    def _apply_damage(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        amount: float,
        *,
        ignore_defense: bool = False,
        label: str = "伤害",
        damage_form: str = "直接",
        defense_rule: str = "普通",
        can_miss: bool = False,
        can_critical: bool = True,
        can_block: bool = True,
        tags: tuple[str, ...] = (),
        allow_reactions: bool = True,
    ) -> DamageResolution:
        effective_defense_rule = (
            "无视防御"
            if ignore_defense and defense_rule == "普通"
            else defense_rule
        )
        resolution = self.damage.resolve(
            DamageRequest(
                amount=max(0.0, float(amount)),
                label=label,
                damage_form=damage_form,
                defense_rule=effective_defense_rule,
                tags=tags,
                can_miss=can_miss,
                can_critical=can_critical,
                can_block=can_block,
            ),
            source=source,
            target=target,
            rng=context.rng,
        )
        if not resolution.hit:
            context.event(
                "miss",
                source,
                target,
                f"{label}被闪避",
                values=resolution.values(),
                tags=tags,
                mechanism=context.current_mechanism,
                dispatch=False,
            )
            self._dispatch_event(
                context,
                kind="闪避后",
                source=source,
                target=target,
                amount=0.0,
                values=resolution.values(),
                tags=tags,
            )
            return resolution

        pre_damage_values: dict[str, Any] = {}
        if damage_form not in {"分摊", "转移"} and resolution.breakdown.limited > 0:
            pre_damage_values = {
                **resolution.values(),
                "待结算伤害": resolution.breakdown.limited,
                "伤害来源ID": source.id,
                "原承受者ID": target.id,
                "伤害标签": list(tags),
            }
            pre_damage_values = self._dispatch_event(
                context,
                kind="造成伤害前",
                source=source,
                target=target,
                amount=resolution.breakdown.limited,
                values=pre_damage_values,
                tags=tags,
            )
            pending = min(
                resolution.breakdown.limited,
                max(
                    0.0,
                    float(
                        pre_damage_values.get(
                            "待结算伤害",
                            resolution.breakdown.limited,
                        )
                    ),
                ),
            )
            resolution = self.damage.with_limited_damage(resolution, pending)

        health_floor = None
        if resolution.defeated:
            context.event(
                "受到致命伤害",
                source,
                target,
                f"{target.name}受到致命伤害",
                resolution.actual_damage,
                values=resolution.values(),
                tags=tags,
                mechanism=context.current_mechanism,
                dispatch=False,
            )
            health_floor = self._try_fatal_guard(
                context,
                source,
                target,
                resolution.actual_damage,
                resolution.values(),
                tags,
            )
        guarded = health_floor is not None
        if health_floor is not None:
            resolution = self.damage.with_minimum_health(resolution, health_floor)
        target.shield = resolution.shield_after
        target.health = resolution.health_after

        actual = resolution.actual_damage
        critical_text = "暴击，" if resolution.critical else ""
        block_text = "格挡，" if resolution.blocked else ""
        event_values = resolution.values()
        for key in ("已分摊伤害", "已转移伤害"):
            if key in pre_damage_values:
                event_values[key] = pre_damage_values[key]
        context.event(
            "damage",
            source,
            target,
            f"{label}{critical_text}{block_text}造成{_number(actual)}点伤害",
            actual,
            values=event_values,
            tags=tags,
            mechanism=context.current_mechanism,
            dispatch=False,
        )
        if actual > 0:
            if resolution.critical:
                self._dispatch_event(
                    context,
                    kind="暴击后",
                    source=source,
                    target=target,
                    amount=actual,
                    values=event_values,
                    tags=tags,
                )
            if resolution.blocked:
                self._dispatch_event(
                    context,
                    kind="格挡后",
                    source=source,
                    target=target,
                    amount=actual,
                    values=event_values,
                    tags=tags,
                )
            self._dispatch_event(
                context,
                kind="造成伤害后",
                source=source,
                target=target,
                amount=actual,
                values=event_values,
                tags=tags,
            )
            self._dispatch_event(
                context,
                kind="受到伤害后",
                source=source,
                target=target,
                amount=actual,
                values=event_values,
                tags=tags,
            )
            if resolution.shield_broken:
                self._dispatch_event(
                    context,
                    kind="护盾破碎后",
                    source=source,
                    target=target,
                    amount=resolution.shield_damage,
                    values=event_values,
                    tags=tags,
                )
        if guarded:
            self._apply_fatal_guard_recovery(context, target)
        if not target.alive:
            self._dispatch_event(
                context,
                kind="死亡后",
                source=source,
                target=target,
                amount=actual,
                values=event_values,
                tags=tags,
            )
            if not target.alive:
                self._dispatch_event(
                    context,
                    kind="击杀后",
                    source=source,
                    target=target,
                    amount=actual,
                    values=event_values,
                    tags=tags,
                )
        if (
            allow_reactions
            and resolution.actual_damage > 0
            and damage_form == "直接"
            and source is not target
            and source.alive
        ):
            reflect = resolution.actual_damage * self._percent(target, "反伤率")
            if reflect > 0:
                self._apply_damage(
                    context,
                    target,
                    source,
                    reflect,
                    label="反伤",
                    damage_form="反伤",
                    defense_rule="真实",
                    can_critical=False,
                    can_block=False,
                    tags=("反伤", "派生伤害"),
                    allow_reactions=False,
                )
            if (
                target.alive
                and source.alive
                and context.rng.random() < self._percent(target, "反击率")
            ):
                self._deal_attack(
                    context,
                    target,
                    source,
                    1.0,
                    "反击",
                    damage_form="直接",
                    tags=("反击", "派生伤害"),
                    allow_followups=False,
                )
        return resolution
    def _use_medicine(self, context: _BattleContext, fighter: _Fighter) -> None:
        if not fighter.auto_medicine:
            return
        self._use_resource_medicine(context, fighter, "恢复血气")
        self._use_resource_medicine(context, fighter, "恢复精神")

    @staticmethod
    def _use_resource_medicine(
        context: _BattleContext,
        fighter: _Fighter,
        effect_type: str,
    ) -> None:
        current = fighter.health if effect_type == "恢复血气" else fighter.spirit
        maximum = fighter.health_max if effect_type == "恢复血气" else fighter.spirit_max
        if maximum <= 0 or current / maximum >= fighter.medicine_threshold:
            return
        candidates = []
        for item_id, quantity in fighter.inventory.items():
            definition = context.item_definitions.get(item_id) or {}
            use = definition.get("使用效果") or {}
            if quantity > 0 and use.get("类型") == effect_type:
                candidates.append((float(use.get("恢复量") or 0), item_id, definition))
        candidates.sort()
        while current / maximum < fighter.medicine_threshold and candidates:
            available = next(
                (value for value in candidates if fighter.inventory.get(value[1], 0) > 0),
                None,
            )
            if available is None:
                break
            amount, item_id, definition = available
            fighter.inventory[item_id] -= 1
            fighter.consumed_items[item_id] = fighter.consumed_items.get(item_id, 0) + 1
            before = current
            applied = min(maximum - current, amount)
            current += applied
            if effect_type == "恢复血气":
                fighter.health = current
            else:
                fighter.spirit = current
            context.event(
                "medicine",
                fighter,
                fighter,
                f"使用{item_id}",
                applied,
                values={
                    "物品": item_id,
                    "资源": "血气" if effect_type == "恢复血气" else "精神",
                    "恢复前": before,
                    "恢复后": current,
                    "实际恢复": applied,
                },
            )


def _number(value: float) -> str:
    rounded = round(float(value), 2)
    return str(int(rounded)) if rounded.is_integer() else str(rounded)


__all__ = [
    "BattleEngine",
    "BattleEvent",
    "BattleOutcome",
    "CombatCatalog",
    "CombatantResult",
    "CombatantSnapshot",
    "StatusState",
]
