"""JSON 机制、状态与事件触发的执行层。"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from .models import BattleContext as _BattleContext
from .models import Fighter as _Fighter
from .models import StatusState


class MechanismRuntime:
    """供战斗编排复用的机制执行能力，不决定行动顺序或奖励。"""

    def _try_fatal_guard(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        event_amount: float,
        event_values: Mapping[str, Any],
        tags: tuple[str, ...],
    ) -> float | None:
        for passive in target.passives:
            mechanism_id, mechanism = self._passive_node(passive)
            if self.catalog.parse_node(mechanism).executor != "监听事件":
                continue
            if mechanism.get("事件") != "受到致命伤害":
                continue
            relation = str(mechanism.get("事件关系") or "自身相关")
            if not self._event_relation_matches(relation, target, source, target):
                continue
            if not self._conditions_allow(
                context,
                source,
                target,
                mechanism.get("条件") or (),
                event_amount,
                event_values,
                tags,
            ):
                continue
            key = (f"{target.id}:{passive.get('实例') or target.id}", mechanism_id)
            per_action = mechanism.get("每次行动最多触发")
            if per_action is not None and context.trigger_counts.get(key, 0) >= int(per_action):
                continue
            used = context.battle_trigger_counts.get(key, 0)
            maximum = max(1, int(mechanism.get("每场战斗最多触发") or 1))
            if used >= maximum:
                continue
            guard_effect = next(
                (
                    dict(effect)
                    for effect in mechanism.get("效果") or ()
                    if self.catalog.parse_node(effect).executor == "抵挡致命伤害"
                ),
                None,
            )
            if guard_effect is None:
                continue
            multiplier = float(passive.get("威力倍率") or 1.0)
            health_floor = max(1.0, float(guard_effect.get("保留血气") or 1) * multiplier)
            context.trigger_counts[key] = context.trigger_counts.get(key, 0) + 1
            context.battle_trigger_counts[key] = used + 1
            context.pending_fatal_guards[target.id] = (mechanism_id, multiplier, mechanism)
            context.event(
                "fatal_guard",
                target,
                target,
                mechanism_id,
                health_floor,
                values={"机制": mechanism_id, "保留血气": health_floor},
                mechanism=mechanism_id,
                dispatch=False,
            )
            return health_floor
        return None

    def _apply_fatal_guard_recovery(self, context: _BattleContext, target: _Fighter) -> None:
        selected = context.pending_fatal_guards.pop(target.id, None)
        if selected is None:
            return
        mechanism_id, multiplier, raw_mechanism = selected
        mechanism = dict(raw_mechanism)
        previous = context.current_mechanism
        context.current_mechanism = mechanism_id
        try:
            for effect in mechanism.get("效果") or ():
                if self.catalog.parse_node(effect).executor == "抵挡致命伤害":
                    continue
                self._execute_mechanism(
                    context,
                    target,
                    target,
                    dict(effect),
                    multiplier,
                    event_amount=0.0,
                    event_values={"保留血气": target.health},
                )
        finally:
            context.current_mechanism = previous

    def _apply_status(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        effect: dict[str, Any],
        multiplier: float,
    ) -> None:
        value = dict(effect.get("状态") or {})
        status_name = str(value.get("名称") or "状态").strip()
        category = str(value.get("分类") or "中性").strip()
        duration = max(1, int(round(float(value.get("持续数值") or 1) * multiplier)))
        blocked_by = "控制状态" if category == "控制" else "负面状态" if category == "负面" else ""
        if blocked_by and any(
            blocked_by in status.effect_immunities for status in target.statuses
        ):
            context.event(
                "status_immune",
                source,
                target,
                f"{target.name}免疫{status_name}",
                values={"状态": status_name, "免疫类型": blocked_by},
                mechanism=context.current_mechanism,
                dispatch=False,
            )
            return
        if category == "控制" and value.get("是否进行控制判定"):
            chance = float(value.get("基础控制命中率") or 100) / 100.0
            chance += self._percent(source, "控制命中率")
            chance -= self._percent(target, "控制抵抗率")
            if context.rng.random() >= self._clamp(chance, 0.0, 0.95):
                context.event(
                    "control_resisted",
                    source,
                    target,
                    f"{status_name}被抵抗",
                    dispatch=False,
                )
                return
            if value.get("是否受韧性影响", True):
                duration = max(1, math.ceil(duration * (1.0 - self._percent(target, "韧性"))))
        flat_damage = 0.0
        damage_ratio = 0.0
        damage_form = "持续"
        defense_rule = "无视防御"
        can_critical = False
        can_block = False
        for trigger in value.get("触发") or ():
            trigger_value = dict(trigger)
            if self.catalog.parse_node(trigger_value).executor != "监听事件":
                continue
            if trigger_value.get("事件") != "行动开始":
                continue
            periodic = next(
                (
                    dict(child)
                    for child in trigger_value.get("效果") or ()
                    if self.catalog.parse_node(child).executor == "造成伤害"
                ),
                None,
            )
            if periodic is None:
                continue
            target_scope = dict(periodic.get("目标") or {}).get("范围")
            if target_scope != "自身":
                raise ValueError(f"状态 {status_name} 的周期伤害目标必须是自身")
            flat_damage = max(
                0.0,
                self._resolve_value(context, periodic.get("数值"), source, target, 0.0, {})
                * multiplier,
            )
            damage_ratio = 0.0
            damage_form = str(periodic.get("伤害形式") or "持续")
            defense_rule = str(periodic.get("防御规则") or "无视防御")
            can_critical = bool(periodic.get("能否暴击", False))
            can_block = bool(periodic.get("能否格挡", False))
            break
        status = StatusState(
            name=status_name,
            category=category,
            remaining_turns=duration,
            source=source.id,
            source_name=source.name,
            source_mechanism=context.current_mechanism,
            source_attack=source.value("攻击", 0.0),
            flat_damage=flat_damage,
            damage_attack_ratio=damage_ratio,
            modifiers={
                str(key): float(amount) * multiplier
                for key, amount in dict(value.get("属性") or {}).items()
            },
            stacks=max(1, int(round(float(value.get("层数") or 1) * multiplier))),
            max_stacks=max(1, int(round(float(value.get("层数上限") or 1) * multiplier))),
            tags=tuple(str(item) for item in value.get("标签") or ()),
            damage_form=damage_form,
            defense_rule=defense_rule,
            can_critical=can_critical,
            can_block=can_block,
            duration_unit=str(value.get("持续单位") or "状态承受者行动"),
            action_limits=tuple(str(item) for item in value.get("行动限制") or ()),
            effect_immunities=tuple(str(item) for item in value.get("效果免疫") or ()),
        )
        existing = next(
            (
                item
                for item in target.statuses
                if item.name == status.name
                and (value.get("叠加范围") != "按效果来源分组" or item.source == status.source)
            ),
            None,
        )
        if existing is None:
            target.statuses.append(status)
        else:
            stacking = str(value.get("重复方式") or "刷新持续")
            if stacking == "不叠加":
                return
            if "增加层数" in stacking:
                existing.stacks = min(existing.max_stacks, existing.stacks + status.stacks)
            if stacking == "延长持续":
                existing.remaining_turns += status.remaining_turns
            elif "刷新" in stacking or stacking == "刷新持续":
                existing.remaining_turns = status.remaining_turns
            else:
                existing.remaining_turns = max(existing.remaining_turns, status.remaining_turns)
            existing.source = status.source
            existing.source_name = status.source_name
            existing.source_mechanism = status.source_mechanism
            existing.source_attack = status.source_attack
            existing.flat_damage = status.flat_damage
            existing.damage_attack_ratio = status.damage_attack_ratio
            existing.modifiers = status.modifiers
            existing.tags = status.tags
            existing.damage_form = status.damage_form
            existing.defense_rule = status.defense_rule
            existing.can_critical = status.can_critical
            existing.can_block = status.can_block
            existing.duration_unit = status.duration_unit
            existing.action_limits = status.action_limits
            existing.effect_immunities = status.effect_immunities
        context.event(
            "status",
            source,
            target,
            f"施加{status.name}，持续{status.remaining_turns}回合",
            values={"状态": status.name, "持续数值": status.remaining_turns, "层数": status.stacks},
            tags=status.tags,
            mechanism=context.current_mechanism,
            dispatch=False,
        )

    def _execute_mechanism_reference(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        mechanism_id: str,
        multiplier: float,
        *,
        event_amount: float = 0.0,
        event_values: Mapping[str, Any] | None = None,
    ) -> None:
        definition = dict(self.catalog.require_mechanism(mechanism_id))
        previous = context.current_mechanism
        context.current_mechanism = str(mechanism_id)
        try:
            self._execute_mechanism(
                context,
                source,
                target,
                definition,
                multiplier,
                event_amount=event_amount,
                event_values=event_values or {},
            )
        finally:
            context.current_mechanism = previous

    def _execute_mechanism(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        effect: dict[str, Any],
        multiplier: float,
        *,
        event_amount: float,
        event_values: Mapping[str, Any],
    ) -> None:
        node = self.catalog.parse_node(effect)
        handler = self._mechanism_handlers.get(node.executor)
        if handler is None:
            raise ValueError(f"战斗核心未实现执行器：{node.executor or '<空>'}")
        handler(
            context,
            source,
            target,
            effect,
            multiplier,
            event_amount=event_amount,
            event_values=event_values,
        )

    def _mechanism_sequence(
        self,
        context,
        source,
        target,
        effect,
        multiplier,
        *,
        event_amount=0.0,
        event_values=None,
        **_,
    ) -> None:
        for child in effect.get("效果") or ():
            self._execute_mechanism(
                context,
                source,
                target,
                dict(child),
                multiplier,
                event_amount=event_amount,
                event_values=event_values or {},
            )

    def _mechanism_conditional(
        self,
        context,
        source,
        target,
        effect,
        multiplier,
        *,
        event_amount=0.0,
        event_values=None,
        **_,
    ) -> None:
        branch = "成立效果" if self._conditions_allow(
            context,
            source,
            target,
            effect.get("条件") or (),
            event_amount,
            event_values or {},
            (),
        ) else "不成立效果"
        for child in effect.get(branch) or ():
            self._execute_mechanism(
                context,
                source,
                target,
                dict(child),
                multiplier,
                event_amount=event_amount,
                event_values=event_values or {},
            )

    def _mechanism_random(
        self,
        context,
        source,
        target,
        effect,
        multiplier,
        *,
        event_amount=0.0,
        event_values=None,
        **_,
    ) -> None:
        options = [dict(value) for value in effect.get("选项") or ()]
        if not options:
            return
        count = max(1, int(effect.get("抽取数量") or 1))
        if effect.get("是否放回"):
            selected = [context.rng.choice(options) for _ in range(count)]
        else:
            selected = context.rng.sample(options, min(count, len(options)))
        for child in selected:
            self._execute_mechanism(
                context,
                source,
                target,
                child,
                multiplier,
                event_amount=event_amount,
                event_values=event_values or {},
            )

    @staticmethod
    def _mechanism_listener(context, source, target, effect, multiplier, **_) -> None:
        del context, source, target, effect, multiplier

    @staticmethod
    def _mechanism_fatal_guard(context, source, target, effect, multiplier, **_) -> None:
        del context, source, target, effect, multiplier

    def _mechanism_reference(
        self,
        context,
        source,
        target,
        effect,
        multiplier,
        *,
        event_amount=0.0,
        event_values=None,
        **_,
    ) -> None:
        self._execute_mechanism_reference(
            context,
            source,
            target,
            str(effect.get("机制") or ""),
            multiplier,
            event_amount=event_amount,
            event_values=event_values or {},
        )

    def _dispatch_event(
        self,
        context: _BattleContext,
        *,
        kind: str,
        source: _Fighter,
        target: _Fighter,
        amount: float,
        values: Mapping[str, Any],
        tags: tuple[str, ...],
    ) -> None:
        if kind not in self.catalog.events or context.event_depth >= 16:
            return
        values = {**dict(values), "事件": kind}
        for owner in context.fighters:
            for passive in owner.passives:
                mechanism_id, mechanism = self._passive_node(passive)
                if self.catalog.parse_node(mechanism).executor != "监听事件":
                    continue
                if mechanism.get("事件") != kind:
                    continue
                relation = str(mechanism.get("事件关系") or "自身相关")
                if not self._event_relation_matches(relation, owner, source, target):
                    continue
                if "派生伤害" in tags and not mechanism.get("接受派生事件", False):
                    continue
                if not self._conditions_allow(
                    context,
                    source,
                    target,
                    mechanism.get("条件") or (),
                    amount,
                    values,
                    tags,
                ):
                    continue
                if not self._trigger_can_resolve(owner, mechanism):
                    continue
                owner_key = f"{owner.id}:{passive.get('实例') or owner.id}"
                activation_key = (owner_key, mechanism_id)
                if activation_key in context.trigger_stack:
                    continue
                per_action = mechanism.get("每次行动最多触发")
                if per_action is not None and context.trigger_counts.get(activation_key, 0) >= int(per_action):
                    continue
                per_battle = mechanism.get("每场战斗最多触发")
                if per_battle is not None and context.battle_trigger_counts.get(activation_key, 0) >= int(per_battle):
                    continue
                context.trigger_counts[activation_key] = context.trigger_counts.get(activation_key, 0) + 1
                context.battle_trigger_counts[activation_key] = context.battle_trigger_counts.get(activation_key, 0) + 1
                context.trigger_stack.add(activation_key)
                context.event_depth += 1
                previous = context.current_mechanism
                context.current_mechanism = mechanism_id
                context.event(
                    "trigger",
                    owner,
                    target,
                    f"{mechanism_id}触发",
                    values={"机制": mechanism_id, "事件": kind},
                    mechanism=mechanism_id,
                    dispatch=False,
                )
                try:
                    for child in mechanism.get("效果") or ():
                        self._execute_mechanism(
                            context,
                            owner,
                            target,
                            dict(child),
                            float(passive.get("威力倍率") or 1.0),
                            event_amount=amount,
                            event_values=values,
                        )
                finally:
                    context.current_mechanism = previous
                    context.event_depth -= 1
                    context.trigger_stack.discard(activation_key)

    @staticmethod
    def _event_relation_matches(
        relation: str,
        owner: _Fighter,
        source: _Fighter,
        target: _Fighter,
    ) -> bool:
        if relation == "自身为来源":
            return source is owner
        if relation == "自身为承受者":
            return target is owner
        if relation == "自身相关":
            return source is owner or target is owner
        if relation == "任意":
            return True
        raise ValueError(f"战斗核心未实现事件关系：{relation}")

    def _trigger_can_resolve(self, owner: _Fighter, mechanism: Mapping[str, Any]) -> bool:
        effects = [dict(value) for value in mechanism.get("效果") or ()]
        if not effects:
            return False
        if all(self.catalog.parse_node(value).executor == "修改技能冷却" for value in effects):
            return any(
                value > 0 and key != owner.current_skill
                for key, value in owner.cooldowns.items()
            )
        return True

    def _passive_node(self, passive: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        mechanism_id = str(passive.get("机制") or "")
        raw_node = passive.get("节点")
        if isinstance(raw_node, Mapping):
            return mechanism_id or "内联被动", dict(raw_node)
        if not mechanism_id:
            raise ValueError("被动技能缺少机制节点")
        return mechanism_id, dict(self.catalog.require_mechanism(mechanism_id))

    def _conditions_allow(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        conditions: Any,
        event_amount: float,
        event_values: Mapping[str, Any],
        tags: tuple[str, ...],
    ) -> bool:
        for raw in conditions:
            condition = dict(raw)
            executor = self.catalog.parse_node(condition).executor
            handler = self._condition_handlers.get(executor)
            if handler is None:
                raise ValueError(f"战斗核心未实现条件执行器：{executor or '<空>'}")
            if not handler(
                context,
                source,
                target,
                condition,
                event_amount,
                event_values,
                tags,
            ):
                return False
        return True

    def _condition_probability(
        self,
        context,
        source,
        target,
        condition,
        event_amount,
        event_values,
        tags,
    ) -> bool:
        del source, target, event_amount, event_values, tags
        chance = float(condition.get("概率") or 0) / 100.0
        return context.rng.random() < self._clamp(chance, 0.0, 1.0)

    def _condition_numeric(
        self,
        context,
        source,
        target,
        condition,
        event_amount,
        event_values,
        tags,
    ) -> bool:
        del tags
        left = self._resolve_value(
            context,
            condition.get("左值"),
            source,
            target,
            event_amount,
            event_values,
        )
        right = self._resolve_value(
            context,
            condition.get("右值"),
            source,
            target,
            event_amount,
            event_values,
        )
        return self._compare(left, right, str(condition.get("比较") or "等于"))

    def _condition_status(
        self,
        context,
        source,
        target,
        condition,
        event_amount,
        event_values,
        tags,
    ) -> bool:
        del context, event_amount, event_values, tags
        destination = self._effect_target(source, target, condition.get("目标"))
        status_name = str(condition.get("状态") or "")
        stacks = sum(status.stacks for status in destination.statuses if status.name == status_name)
        relation = str(condition.get("比较") or "存在")
        if relation == "存在":
            return stacks > 0
        if relation == "不存在":
            return stacks == 0
        expected = int(condition.get("层数") or 1)
        return self._compare(stacks, expected, relation.removeprefix("层数"))

    @staticmethod
    def _condition_type(
        context,
        source,
        target,
        condition,
        event_amount,
        event_values,
        tags,
    ) -> bool:
        del context, source, target, event_amount, tags
        key = str(condition.get("类型") or "")
        aliases = {"资源类型": "资源", "行动类型": "行动类型"}
        return str(event_values.get(aliases.get(key, key), "")) == str(condition.get("值") or "")

    def _condition_combined(
        self,
        context,
        source,
        target,
        condition,
        event_amount,
        event_values,
        tags,
    ) -> bool:
        values = [
            self._conditions_allow(
                context,
                source,
                target,
                (child,),
                event_amount,
                event_values,
                tags,
            )
            for child in condition.get("条件") or ()
        ]
        relation = str(condition.get("关系") or "全部成立")
        if relation == "全部成立":
            return all(values)
        if relation == "任一成立":
            return any(values)
        if relation == "全部不成立":
            return not any(values)
        raise ValueError(f"战斗核心未实现组合条件关系：{relation}")

    @staticmethod
    def _condition_tags(
        context,
        source,
        target,
        condition,
        event_amount,
        event_values,
        tags,
    ) -> bool:
        del context, source, target, event_amount, event_values
        required = set(str(value) for value in condition.get("标签") or ())
        relation = str(condition.get("关系") or "包含全部")
        if relation == "包含任一":
            return not required or bool(required.intersection(tags))
        if relation == "包含全部":
            return required.issubset(tags)
        if relation == "全部不含":
            return not required.intersection(tags)
        raise ValueError(f"战斗核心未实现标签关系：{relation}")

    @staticmethod
    def _compare(left: float, right: float, relation: str) -> bool:
        if relation == "小于":
            return left < right
        if relation == "小于等于":
            return left <= right
        if relation == "等于":
            return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
        if relation == "不等于":
            return not math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
        if relation == "大于等于":
            return left >= right
        if relation == "大于":
            return left > right
        raise ValueError(f"战斗核心未实现数值比较：{relation}")

    def _mechanism_damage(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        effect: dict[str, Any],
        multiplier: float,
        event_amount: float = 0.0,
        event_values: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> None:
        destination = self._effect_target(source, target, effect.get("目标"))
        amount = max(
            0.0,
            self._resolve_value(
                context,
                effect.get("数值"),
                source,
                destination,
                event_amount,
                event_values or {},
            )
            * multiplier,
        )
        if source.current_skill:
            amount *= max(0.0, 1.0 + self._percent(source, "技能威力"))
        damage_form = str(effect.get("伤害形式") or "直接")
        defense_rule = str(effect.get("防御规则") or "普通")
        tags = tuple(str(value) for value in effect.get("标签") or ())
        self._deal_attack(
            context,
            source,
            destination,
            0.0,
            str(effect.get("名称") or context.current_mechanism or "机制伤害"),
            damage_form=damage_form,
            defense_rule=defense_rule,
            tags=tags,
            can_miss=damage_form == "直接",
            can_critical=bool(effect.get("能否暴击", False)),
            can_block=bool(effect.get("能否格挡", True)),
            allow_followups=False,
            raw_amount=amount,
            can_lifesteal=bool(effect.get("能否触发吸血", False)),
        )

    def _mechanism_recover_resource(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        effect: dict[str, Any],
        multiplier: float,
        *,
        event_amount: float = 0.0,
        event_values: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> None:
        destination = self._effect_target(source, target, effect.get("目标", "自身"))
        resource = str(effect.get("资源") or "")
        amount = max(
            0.0,
            self._resolve_value(
                context,
                effect.get("数值"),
                source,
                destination,
                event_amount,
                event_values or {},
            )
            * multiplier,
        )
        if resource == "血气":
            amount *= max(0.0, 1.0 + self._percent(source, "治疗加成") + self._percent(destination, "受疗加成"))
        elif resource == "护盾":
            amount *= max(0.0, 1.0 + self._percent(source, "护盾加成") + self._percent(destination, "受盾加成"))
        before, maximum = self._resource_values(destination, resource)
        after = min(maximum, before + amount)
        self._set_resource(destination, resource, after)
        applied = after - before
        if applied > 0:
            values = {
                "资源": resource,
                "实际恢复": applied,
                "实际护盾": applied if resource == "护盾" else 0,
            }
            context.event(
                "recover",
                source,
                destination,
                f"{context.current_mechanism or '机制'}恢复{_number(applied)}点{resource}",
                applied,
                values=values,
                mechanism=context.current_mechanism,
                dispatch=False,
            )
            self._dispatch_event(
                context,
                kind="获得护盾后" if resource == "护盾" else "恢复后",
                source=source,
                target=destination,
                amount=applied,
                values=values,
                tags=(),
            )

    def _mechanism_consume_resource(
        self,
        context,
        source,
        target,
        effect,
        multiplier,
        *,
        event_amount=0.0,
        event_values=None,
        **_,
    ) -> None:
        destination = self._effect_target(source, target, effect.get("目标"))
        if any("资源消耗" in status.effect_immunities for status in destination.statuses):
            return
        resource = str(effect.get("资源") or "")
        amount = max(
            0.0,
            self._resolve_value(
                context,
                effect.get("数值"),
                source,
                destination,
                event_amount,
                event_values or {},
            )
            * multiplier,
        )
        before, _maximum = self._resource_values(destination, resource)
        if before < amount and effect.get("不足时是否失败", True):
            context.event(
                "resource_failed",
                source,
                destination,
                f"{resource}不足",
                amount,
                values={"资源": resource, "需要": amount, "现有": before},
                mechanism=context.current_mechanism,
                dispatch=False,
            )
            return
        applied = min(before, amount)
        self._set_resource(destination, resource, before - applied)
        if applied > 0:
            values = {"资源": resource, "实际消耗": applied}
            context.event(
                "resource_cost",
                source,
                destination,
                f"消耗{_number(applied)}点{resource}",
                applied,
                values=values,
                mechanism=context.current_mechanism,
                dispatch=False,
            )
            self._dispatch_event(
                context,
                kind="资源消耗后",
                source=source,
                target=destination,
                amount=applied,
                values=values,
                tags=(),
            )
            if resource == "护盾" and before > 0 and before - applied <= 0:
                self._dispatch_event(
                    context,
                    kind="护盾破碎后",
                    source=source,
                    target=destination,
                    amount=applied,
                    values={"资源": resource, "护盾伤害": applied},
                    tags=(),
                )

    def _mechanism_set_resource(
        self,
        context,
        source,
        target,
        effect,
        multiplier,
        *,
        event_amount=0.0,
        event_values=None,
        **_,
    ) -> None:
        destination = self._effect_target(source, target, effect.get("目标"))
        resource = str(effect.get("资源") or "")
        before, maximum = self._resource_values(destination, resource)
        requested = self._resolve_value(
            context,
            effect.get("数值"),
            source,
            destination,
            event_amount,
            event_values or {},
        ) * multiplier
        after = self._clamp(requested, 0.0, maximum)
        self._set_resource(destination, resource, after)
        context.event(
            "resource_set",
            source,
            destination,
            f"{resource}由{_number(before)}变为{_number(after)}",
            after - before,
            values={"资源": resource, "原数值": before, "现数值": after},
            mechanism=context.current_mechanism,
            dispatch=False,
        )
        if resource == "护盾" and before > 0 and after <= 0:
            self._dispatch_event(
                context,
                kind="护盾破碎后",
                source=source,
                target=destination,
                amount=before,
                values={"资源": resource, "护盾伤害": before},
                tags=(),
            )

    def _mechanism_transfer_resource(
        self,
        context,
        source,
        target,
        effect,
        multiplier,
        *,
        event_amount=0.0,
        event_values=None,
        **_,
    ) -> None:
        origin = self._effect_target(source, target, effect.get("来源目标"))
        destination = self._effect_target(source, target, effect.get("接收目标"))
        source_resource = str(effect.get("来源资源") or "")
        target_resource = str(effect.get("接收资源") or "")
        requested = max(
            0.0,
            self._resolve_value(
                context,
                effect.get("数值"),
                source,
                origin,
                event_amount,
                event_values or {},
            )
            * multiplier,
        )
        available, _ = self._resource_values(origin, source_resource)
        receiving, maximum = self._resource_values(destination, target_resource)
        if available < requested and effect.get("不足时是否失败", False):
            return
        moved = min(requested, available, max(0.0, maximum - receiving))
        if moved <= 0:
            return
        self._set_resource(origin, source_resource, available - moved)
        self._set_resource(destination, target_resource, receiving + moved)
        context.event(
            "resource_transfer",
            source,
            destination,
            f"转移{_number(moved)}点{source_resource}",
            moved,
            values={"来源资源": source_resource, "接收资源": target_resource, "实际转移": moved},
            mechanism=context.current_mechanism,
            dispatch=False,
        )

    def _mechanism_add_status(self, context, source, target, effect, multiplier, **_):
        destination = self._effect_target(source, target, effect.get("目标"))
        self._apply_status(
            context,
            source,
            destination,
            {"状态": dict(effect.get("状态") or {})},
            multiplier,
        )

    def _matching_statuses(self, fighter: _Fighter, effect: Mapping[str, Any]) -> list[StatusState]:
        name = str(effect.get("状态") or "")
        category = str(effect.get("分类") or "全部")
        matches = [
            status
            for status in fighter.statuses
            if (not name or status.name == name)
            and (category == "全部" or status.category == category)
        ]
        if effect.get("顺序") == "随机":
            return matches
        if effect.get("顺序") == "先获得":
            return matches
        return list(reversed(matches))

    def _selected_statuses(
        self,
        context: _BattleContext,
        fighter: _Fighter,
        effect: Mapping[str, Any],
    ) -> list[StatusState]:
        matches = self._matching_statuses(fighter, effect)
        if effect.get("顺序") == "随机":
            context.rng.shuffle(matches)
        if effect.get("选择全部"):
            return matches
        return matches[: max(1, int(effect.get("数量") or 1))]

    def _mechanism_remove_status(self, context, source, target, effect, multiplier, **_):
        destination = self._effect_target(source, target, effect.get("目标"))
        selection = dict(effect)
        selection["数量"] = max(1, int(round(float(effect.get("数量") or 1) * multiplier)))
        selected = self._selected_statuses(context, destination, selection)
        for status in selected:
            if status not in destination.statuses:
                continue
            destination.statuses.remove(status)
            context.event(
                "status_end",
                source,
                destination,
                f"移除{status.name}",
                values={"状态": status.name, "分类": status.category},
                mechanism=context.current_mechanism,
                dispatch=False,
            )

    def _mechanism_modify_status_stacks(self, context, source, target, effect, multiplier, **_):
        destination = self._effect_target(source, target, effect.get("目标"))
        selected = next(
            (status for status in reversed(destination.statuses) if status.name == str(effect.get("状态") or "")),
            None,
        )
        if selected is None:
            return
        amount = max(1, int(round(int(effect.get("层数") or 1) * multiplier)))
        before = selected.stacks
        executor = self.catalog.parse_node(effect).ability
        if executor == "增加状态层数":
            selected.stacks = min(selected.max_stacks, selected.stacks + amount)
        else:
            if selected.stacks < amount and effect.get("不足时是否失败", True):
                return
            selected.stacks = max(0, selected.stacks - amount)
        if selected.stacks <= 0:
            destination.statuses.remove(selected)
        context.event(
            "status_stack",
            source,
            destination,
            f"{selected.name}层数由{before}变为{selected.stacks}",
            selected.stacks - before,
            values={"状态": selected.name, "原层数": before, "现层数": selected.stacks},
            mechanism=context.current_mechanism,
            dispatch=False,
        )

    def _mechanism_modify_status_duration(self, context, source, target, effect, multiplier, **_):
        destination = self._effect_target(source, target, effect.get("目标"))
        selected = next(
            (status for status in reversed(destination.statuses) if status.name == str(effect.get("状态") or "")),
            None,
        )
        if selected is None or selected.duration_unit == "整场战斗":
            return
        amount = max(1, int(round(int(effect.get("持续数值") or 1) * multiplier)))
        before = selected.remaining_turns
        ability = self.catalog.parse_node(effect).ability
        selected.remaining_turns = before + amount if ability == "延长状态" else max(0, before - amount)
        if selected.remaining_turns <= 0:
            destination.statuses.remove(selected)
        context.event(
            "status_duration",
            source,
            destination,
            f"{selected.name}剩余行动由{before}变为{selected.remaining_turns}",
            selected.remaining_turns - before,
            values={"状态": selected.name, "原持续": before, "现持续": selected.remaining_turns},
            mechanism=context.current_mechanism,
            dispatch=False,
        )

    def _mechanism_copy_status(self, context, source, target, effect, multiplier, **_):
        origin = self._effect_target(source, target, effect.get("来源目标"))
        destination = self._effect_target(source, target, effect.get("接收目标"))
        selection = dict(effect)
        selection["数量"] = max(1, int(round(float(effect.get("数量") or 1) * multiplier)))
        for status in self._selected_statuses(context, origin, selection):
            copied = StatusState.from_dict(status.to_dict())
            destination.statuses.append(copied)
            context.event(
                "status",
                source,
                destination,
                f"复制{status.name}",
                values={"状态": status.name},
                mechanism=context.current_mechanism,
                dispatch=False,
            )

    def _mechanism_transfer_status(self, context, source, target, effect, multiplier, **_):
        origin = self._effect_target(source, target, effect.get("来源目标"))
        destination = self._effect_target(source, target, effect.get("接收目标"))
        selection = dict(effect)
        selection["数量"] = max(1, int(round(float(effect.get("数量") or 1) * multiplier)))
        for status in self._selected_statuses(context, origin, selection):
            if status not in origin.statuses:
                continue
            origin.statuses.remove(status)
            destination.statuses.append(status)
            context.event(
                "status",
                source,
                destination,
                f"转移{status.name}",
                values={"状态": status.name},
                mechanism=context.current_mechanism,
                dispatch=False,
            )

    def _mechanism_modify_action_progress(self, context, source, target, effect, multiplier, **_):
        destination = self._effect_target(source, target, effect.get("目标"))
        if any("行动条修改" in status.effect_immunities for status in destination.statuses):
            return
        amount = float(effect.get("数值") or 0) * multiplier / 100.0
        before = context.action_progress.get(destination.id, 0.0)
        mode = str(effect.get("方式") or "增加")
        if mode == "增加":
            after = before + amount
        elif mode == "减少":
            after = before - amount
        elif mode == "设置":
            after = amount
        else:
            raise ValueError(f"战斗核心未实现行动条修改方式：{mode}")
        context.action_progress[destination.id] = self._clamp(after, 0.0, 1.0 - 1e-12)
        context.event(
            "action_progress",
            source,
            destination,
            f"行动准备由{_number(before * 100)}%变为{_number(context.action_progress[destination.id] * 100)}%",
            (context.action_progress[destination.id] - before) * 100,
            values={"原行动条": before * 100, "现行动条": context.action_progress[destination.id] * 100},
            mechanism=context.current_mechanism,
            dispatch=False,
        )

    def _mechanism_revive(self, context, source, target, effect, multiplier, **_):
        destination = self._effect_target(source, target, effect.get("目标"))
        if destination.alive:
            return
        destination.health = min(
            destination.health_max,
            max(
                1.0,
                destination.health_max * float(effect.get("血气百分比") or 100) * multiplier / 100.0,
            ),
        )
        destination.spirit = destination.spirit_max * float(effect.get("精神百分比", 100)) / 100.0
        if effect.get("移除负面状态", True):
            destination.statuses = [
                status for status in destination.statuses if status.category not in {"负面", "控制"}
            ]
        context.event(
            "revive",
            source,
            destination,
            f"{destination.name}复起",
            destination.health,
            values={"恢复血气": destination.health, "恢复精神": destination.spirit},
            mechanism=context.current_mechanism,
            dispatch=False,
        )

    def _mechanism_modify_cooldown(self, context, source, target, effect, multiplier, **_):
        destination = self._effect_target(source, target, effect.get("目标"))
        if any("冷却修改" in status.effect_immunities for status in destination.statuses):
            return
        amount = max(0, int(round(float(effect.get("数值") or 0) * multiplier)))
        mode = str(effect.get("方式") or "减少")
        selected = self._select_skills(context, destination, effect.get("技能"))
        if not selected or (amount <= 0 and mode != "清空"):
            return
        for key in selected:
            before = destination.cooldowns.get(key, 0)
            if mode == "清空":
                after = 0
            elif mode == "设置":
                after = amount
            elif mode == "增加":
                after = before + amount
            elif mode == "减少":
                after = before - amount
            else:
                raise ValueError(f"当前战斗核心尚未实现冷却修改方式：{mode}")
            destination.cooldowns[key] = max(0, after)
            context.event(
                "cooldown",
                source,
                destination,
                f"技能冷却由{before}变为{destination.cooldowns[key]}",
                values={"技能键": key, "原冷却": before, "现冷却": destination.cooldowns[key]},
                mechanism=context.current_mechanism,
                dispatch=False,
            )

    def _select_skills(
        self,
        context: _BattleContext,
        fighter: _Fighter,
        raw_selector: Any,
    ) -> list[str]:
        selector = dict(raw_selector or {})
        executor = self.catalog.parse_node(selector).executor
        handler = self._skill_selector_handlers.get(executor)
        if handler is None:
            raise ValueError(f"战斗核心未实现技能选择执行器：{executor or '<空>'}")
        return handler(context, fighter, selector)

    @staticmethod
    def _skills_select(
        context: _BattleContext,
        fighter: _Fighter,
        selector: Mapping[str, Any],
    ) -> list[str]:
        scope = str(selector.get("范围") or "冷却中的技能")
        skills = {skill.key: skill for skill in fighter.skills}
        if scope == "冷却中的技能":
            candidates = [
                key
                for key, value in fighter.cooldowns.items()
                if value > 0 and key != fighter.current_skill
            ]
        elif scope == "全部技能":
            candidates = [key for key in skills if key != fighter.current_skill]
        elif scope == "当前技能":
            candidates = [fighter.current_skill] if fighter.current_skill else []
        elif scope == "指定技能":
            name = str(selector.get("名称") or "")
            candidates = [key for key, skill in skills.items() if key == name or skill.name == name]
        else:
            raise ValueError(f"当前战斗核心尚未实现技能范围：{scope}")
        order = str(selector.get("排序") or "无")
        if order == "随机":
            candidates = list(candidates)
            context.rng.shuffle(candidates)
        elif order == "冷却从低到高":
            candidates.sort(key=lambda key: (fighter.cooldowns.get(key, 0), key))
        elif order == "冷却从高到低":
            candidates.sort(key=lambda key: (-fighter.cooldowns.get(key, 0), key))
        elif order != "无":
            raise ValueError(f"当前战斗核心尚未实现技能排序：{order}")
        quantity = max(1, int(selector.get("数量") or 1))
        return candidates if selector.get("选择全部") else candidates[:quantity]

    def _resolve_value(
        self,
        context: _BattleContext,
        value: Any,
        source: _Fighter,
        target: _Fighter,
        event_amount: float,
        event_values: Mapping[str, Any],
    ) -> float:
        if isinstance(value, bool):
            raise ValueError("战斗数值不能是布尔值")
        if isinstance(value, int | float):
            return float(value)
        spec = dict(value or {})
        executor = self.catalog.parse_node(spec).executor
        handler = self._value_handlers.get(executor)
        if handler is None:
            raise ValueError(f"战斗核心未实现数值执行器：{executor or '<空>'}")
        return handler(context, spec, source, target, event_amount, event_values)

    def _value_read(
        self,
        context: _BattleContext,
        spec: Mapping[str, Any],
        source: _Fighter,
        target: _Fighter,
        event_amount: float,
        event_values: Mapping[str, Any],
    ) -> float:
        origin = str(spec.get("来源") or "固定值")
        selected = (
            self._effect_target(source, target, spec.get("目标"))
            if spec.get("目标") is not None
            else target
        )
        if origin == "本次伤害":
            result = float(event_values.get("实际伤害", event_amount))
        elif origin in {"自身属性", "效果来源属性"}:
            result = source.value(str(spec.get("属性") or ""), 0.0)
        elif origin in {"目标属性", "当前目标属性"}:
            result = selected.value(str(spec.get("属性") or ""), 0.0)
        elif origin == "自身当前血气":
            result = source.health
        elif origin == "自身已损失血气":
            result = max(0.0, source.health_max - source.health)
        elif origin == "自身当前精神":
            result = source.spirit
        elif origin == "自身已损失精神":
            result = max(0.0, source.spirit_max - source.spirit)
        elif origin == "自身当前护盾":
            result = source.shield
        elif origin == "目标当前血气":
            result = selected.health
        elif origin == "目标已损失血气":
            result = max(0.0, selected.health_max - selected.health)
        elif origin == "目标当前精神":
            result = selected.spirit
        elif origin == "目标已损失精神":
            result = max(0.0, selected.spirit_max - selected.spirit)
        elif origin == "目标当前护盾":
            result = selected.shield
        elif origin == "本次恢复":
            result = float(event_values.get("实际恢复", event_amount))
        elif origin == "本次护盾":
            result = float(event_values.get("实际护盾", event_amount))
        elif origin == "本次资源消耗":
            result = float(event_values.get("实际消耗", event_amount))
        elif origin == "状态层数":
            status_name = str(spec.get("状态") or "")
            result = float(sum(status.stacks for status in selected.statuses if status.name == status_name))
        else:
            result = float(spec.get("固定值", spec.get("数值", 0)) or 0)
        if "百分比" in spec:
            result *= float(spec.get("百分比") or 0) / 100.0
        if "最低值" in spec:
            result = max(float(spec["最低值"]), result)
        if "最高值" in spec:
            result = min(float(spec["最高值"]), result)
        return result

    def _value_calculate(
        self,
        context: _BattleContext,
        spec: Mapping[str, Any],
        source: _Fighter,
        target: _Fighter,
        event_amount: float,
        event_values: Mapping[str, Any],
    ) -> float:
        left = self._resolve_value(context, spec.get("左值"), source, target, event_amount, event_values)
        right = self._resolve_value(context, spec.get("右值"), source, target, event_amount, event_values)
        mode = str(spec.get("方式") or "相加")
        if mode == "相加":
            result = left + right
        elif mode == "相减":
            result = left - right
        elif mode == "相乘":
            result = left * right
        elif mode == "相除":
            if math.isclose(right, 0.0, abs_tol=1e-12):
                raise ValueError("战斗数值不能除以零")
            result = left / right
        elif mode == "取最小":
            result = min(left, right)
        elif mode == "取最大":
            result = max(left, right)
        elif mode == "平均":
            result = (left + right) / 2.0
        else:
            raise ValueError(f"战斗核心未实现数值计算方式：{mode}")
        if "最低值" in spec:
            result = max(float(spec["最低值"]), result)
        if "最高值" in spec:
            result = min(float(spec["最高值"]), result)
        return round(result, int(spec.get("保留小数位", 2)))

    def _value_random(
        self,
        context: _BattleContext,
        spec: Mapping[str, Any],
        source: _Fighter,
        target: _Fighter,
        event_amount: float,
        event_values: Mapping[str, Any],
    ) -> float:
        low = self._resolve_value(context, spec.get("最低值"), source, target, event_amount, event_values)
        high = self._resolve_value(context, spec.get("最高值"), source, target, event_amount, event_values)
        low, high = sorted((low, high))
        if spec.get("取整", True):
            minimum = math.ceil(low)
            maximum = math.floor(high)
            if minimum > maximum:
                return float(round(context.rng.uniform(low, high)))
            return float(context.rng.randint(minimum, maximum))
        return context.rng.uniform(low, high)

    def _effect_target(self, source: _Fighter, target: _Fighter, value: Any) -> _Fighter:
        selector = dict(value or {})
        executor = self.catalog.parse_node(selector).executor
        handler = self._target_handlers.get(executor)
        if handler is None:
            raise ValueError(f"战斗核心未实现目标执行器：{executor or '<空>'}")
        return handler(source, target, selector)

    @staticmethod
    def _target_select(
        source: _Fighter,
        target: _Fighter,
        selector: Mapping[str, Any],
    ) -> _Fighter:
        scope = str(selector.get("范围") or "当前目标")
        if scope in {"自身", "效果来源", "己方"}:
            return source
        if scope in {"当前目标", "敌方"}:
            return target
        raise ValueError(f"当前战斗核心尚未实现目标范围：{scope or '<空>'}")

    @staticmethod
    def _resource_values(target: _Fighter, resource: str) -> tuple[float, float]:
        if resource == "血气":
            return target.health, target.health_max
        if resource == "精神":
            return target.spirit, target.spirit_max
        if resource == "护盾":
            return target.shield, target.shield_max
        raise ValueError(f"战斗核心未定义资源：{resource or '<空>'}")

    @staticmethod
    def _set_resource(target: _Fighter, resource: str, value: float) -> None:
        if resource == "血气":
            target.health = value
        elif resource == "精神":
            target.spirit = value
        elif resource == "护盾":
            target.shield = value
        else:
            raise ValueError(f"战斗核心未定义资源：{resource or '<空>'}")

    @staticmethod
    def _percent(target: _Fighter, attribute: str, default: float = 0.0) -> float:
        if attribute not in target.attributes and not any(attribute in status.modifiers for status in target.statuses):
            return float(default)
        return target.value(attribute, default * 100.0) / 100.0

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return min(maximum, max(minimum, float(value)))


def _number(value: float) -> str:
    rounded = round(float(value), 2)
    return str(int(rounded)) if rounded.is_integer() else str(rounded)


__all__ = ["MechanismRuntime"]
