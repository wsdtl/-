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
            health_floor = max(1.0, float(guard_effect.get("保留血气") or 1))
            context.trigger_counts[key] = context.trigger_counts.get(key, 0) + 1
            context.battle_trigger_counts[key] = used + 1
            multiplier = float(passive.get("威力倍率") or 1.0)
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
        duration = max(1, int(value.get("持续数值") or 1))
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
                self._resolve_value(periodic.get("数值"), source, target, 0.0, {})
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
            stacks=max(1, int(value.get("层数") or 1)),
            max_stacks=max(1, int(value.get("层数上限") or 1)),
            tags=tuple(str(item) for item in value.get("标签") or ()),
            damage_form=damage_form,
            defense_rule=defense_rule,
            can_critical=can_critical,
            can_block=can_block,
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
            if "增加层数" in stacking:
                existing.stacks = min(existing.max_stacks, existing.stacks + status.stacks)
            if "刷新" in stacking or stacking == "刷新持续":
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

    def _mechanism_damage(
        self,
        context: _BattleContext,
        source: _Fighter,
        target: _Fighter,
        effect: dict[str, Any],
        multiplier: float,
        **_: Any,
    ) -> None:
        destination = self._effect_target(source, target, effect.get("目标"))
        amount = max(
            0.0,
            self._resolve_value(
                effect.get("数值"),
                source,
                destination,
                0.0,
                {},
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
            self._resolve_value(effect.get("数值"), source, destination, event_amount, event_values or {})
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
            context.event(
                "recover",
                source,
                destination,
                f"{context.current_mechanism or '机制'}恢复{_number(applied)}点{resource}",
                applied,
                values={"资源": resource, "实际恢复": applied},
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

    def _mechanism_modify_cooldown(self, context, source, target, effect, multiplier, **_):
        amount = max(0, int(round(float(effect.get("数值") or 0) * multiplier)))
        mode = str(effect.get("方式") or "减少")
        destination = self._effect_target(source, target, effect.get("目标"))
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
        if selector.get("范围") != "冷却中的技能":
            raise ValueError("当前战斗核心只支持选择冷却中的技能")
        candidates = [
            key
            for key, value in fighter.cooldowns.items()
            if value > 0 and key != fighter.current_skill
        ]
        order = str(selector.get("排序") or "无")
        if order == "随机":
            candidates = list(candidates)
            context.rng.shuffle(candidates)
        elif order == "冷却从低到高":
            candidates.sort(key=lambda key: (fighter.cooldowns[key], key))
        elif order == "冷却从高到低":
            candidates.sort(key=lambda key: (-fighter.cooldowns[key], key))
        elif order != "无":
            raise ValueError(f"当前战斗核心尚未实现技能排序：{order}")
        quantity = max(1, int(selector.get("数量") or 1))
        return candidates if selector.get("选择全部") else candidates[:quantity]

    def _resolve_value(
        self,
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
        return handler(spec, source, target, event_amount, event_values)

    @staticmethod
    def _value_read(
        spec: Mapping[str, Any],
        source: _Fighter,
        target: _Fighter,
        event_amount: float,
        event_values: Mapping[str, Any],
    ) -> float:
        origin = str(spec.get("来源") or "固定值")
        if origin == "本次伤害":
            result = float(event_values.get("实际伤害", event_amount))
        elif origin in {"自身属性", "效果来源属性"}:
            result = source.value(str(spec.get("属性") or ""), 0.0)
        elif origin in {"目标属性", "当前目标属性"}:
            result = target.value(str(spec.get("属性") or ""), 0.0)
        elif origin == "自身当前血气":
            result = source.health
        elif origin == "自身当前精神":
            result = source.spirit
        elif origin == "自身已损失精神":
            result = max(0.0, source.spirit_max - source.spirit)
        else:
            result = float(spec.get("固定值", spec.get("数值", 0)) or 0)
        if "百分比" in spec:
            result *= float(spec.get("百分比") or 0) / 100.0
        if "最低值" in spec:
            result = max(float(spec["最低值"]), result)
        if "最高值" in spec:
            result = min(float(spec["最高值"]), result)
        return result

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
        if scope in {"自身", "效果来源"}:
            return source
        if scope == "当前目标":
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
