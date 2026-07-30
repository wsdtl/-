"""功法实例与 JSON 战斗效果的完整可读展示。"""

from __future__ import annotations

import asyncio
from typing import Any

from game.app import current_game_services
from message import M


async def handle(message: str, context, client_id: str, manager) -> None:
    services = current_game_services()
    user_id = context.identity.primary.external_id
    await asyncio.to_thread(services.player.ensure, user_id, context.sender_name)
    parts = str(message or "").split()
    if not parts:
        await _show_slots(services, user_id, client_id, manager)
        return
    if parts[0] == "装配":
        await _equip(parts, services, user_id, client_id, manager)
        return
    if parts[0] == "卸下":
        await _unequip(parts, services, user_id, client_id, manager)
        return
    if len(parts) != 1 or not parts[0].isdigit():
        await manager.send(_error("用法：功法 编号"), client_id)
        return
    technique = await asyncio.to_thread(services.player.technique, user_id, int(parts[0]))
    if technique is None:
        await manager.send(_error("没有找到这本功法。"), client_id)
        return
    await manager.send(_detail(services, technique), client_id)


async def _show_slots(services, user_id: str, client_id: str, manager) -> None:
    assets = await asyncio.to_thread(services.player.load, user_id)
    by_slot = {
        value.equipped_slot: value
        for value in assets.techniques
        if value.equipped_slot is not None
    }
    reply = M.document().section("功法", icon="skill")
    for slot in range(1, 7):
        value = by_slot.get(slot)
        if value is None:
            reply.line(f"{slot}位：空")
            continue
        reply.line(
            f"{slot}位：",
            M.command(
                f"{value.grade_id}·{value.technique_id}",
                f"功法 {value.born_order}",
            ),
        )
    reply.line(M.command("查看全部功法", "纳戒 功法 1"), " | ", M.command("返回状态", "状态"))
    await manager.send(reply.build(), client_id)


async def _equip(parts, services, user_id: str, client_id: str, manager) -> None:
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await manager.send(_error("用法：功法 装配 编号 位置"), client_id)
        return
    status = await asyncio.to_thread(
        services.player.equip_technique,
        user_id,
        int(parts[1]),
        int(parts[2]),
    )
    text = {
        "equipped": f"已装配至第{int(parts[2])}位。",
        "invalid_slot": "功法位置只能是1至6。",
        "not_found": "没有找到这本功法。",
        "duplicate_name": "同名功法不能同时装配。",
        "incompatible": "这本功法与当前功法、附魔或宝石无法共同运转。",
    }[status]
    await manager.send(
        M.document()
        .section("功法装配", icon="skill")
        .line(text)
        .line(M.command("查看功法", "功法"))
        .build(),
        client_id,
    )


async def _unequip(parts, services, user_id: str, client_id: str, manager) -> None:
    if len(parts) != 2 or not parts[1].isdigit():
        await manager.send(_error("用法：功法 卸下 位置"), client_id)
        return
    slot = int(parts[1])
    if slot < 1 or slot > 6:
        await manager.send(_error("功法位置只能是1至6。"), client_id)
        return
    status = await asyncio.to_thread(services.player.unequip_technique, user_id, slot)
    text = {
        "unequipped": "已卸下。",
        "empty_slot": "这个位置原本就是空的。",
        "incompatible": "当前还有功法、附魔或宝石依赖它，暂时不能卸下。",
    }[status]
    await manager.send(
        M.document()
        .section("功法卸下", icon="skill")
        .line(text)
        .line(M.command("查看功法", "功法"))
        .build(),
        client_id,
    )


def _detail(services, technique):
    definition = services.content.technique_definitions[technique.technique_id]
    grade = services.content.grade_definitions[technique.grade_id]
    multiplier = float(grade["能力倍率"])
    attribute_definitions = services.content.attribute_definitions
    reply = (
        M.document()
        .section(f"{technique.grade_id}·{technique.technique_id}", icon="skill")
        .row(("编号", technique.born_order), ("评分", technique.score))
        .line(str(definition.get("说明") or ""))
    )
    if technique.equipped_slot is None:
        reply.field("装配", "未装配")
    else:
        reply.field("装配", f"第{technique.equipped_slot}位")

    if technique.affixes:
        reply.line("随机词条：")
        for affix in technique.affixes:
            reply.line(
                f"{affix['词条']}：",
                _attribute_value(
                    str(affix["属性"]),
                    float(affix["数值"]),
                    attribute_definitions,
                ),
            )

    abilities = services.content.atomic_ability_definitions
    mechanisms = services.content.mechanism_definitions
    for node in definition.get("组成") or ():
        executor = services.content.ability_executor(dict(node))
        if executor == "装配属性":
            reply.line("固定属性：")
            for key, amount in dict(node.get("属性") or {}).items():
                reply.line(_attribute_value(str(key), float(amount), attribute_definitions))
        elif executor == "装配主动技能":
            reply.line("主动功法：", str(node.get("名称") or technique.technique_id))
            reply.row(
                ("消耗精神", _number(float(node.get("精神消耗") or 0))),
                ("冷却", f"{int(node.get('冷却行动') or 0)}次自身行动"),
            )
            _append_effects(reply, node, multiplier, attribute_definitions, abilities, mechanisms)
        elif executor == "装配被动技能":
            reply.line("被动功法：", str(node.get("名称") or technique.technique_id))
            _append_effects(reply, node, multiplier, attribute_definitions, abilities, mechanisms)

    if technique.equipped_slot is None:
        reply.line(M.command("装配", f"功法 装配 {technique.born_order} ", submit=False))
    else:
        reply.line(M.command("卸下", f"功法 卸下 {technique.equipped_slot}"))
    reply.line(M.command("返回功法", "功法"), " | ", M.command("返回纳戒", "纳戒 功法 1"))
    return reply.build()


def _mechanism_text(
    mechanism: dict[str, Any],
    multiplier: float,
    attribute_definitions: dict[str, dict[str, Any]],
    *,
    include_trigger: bool = True,
    ability_definitions: dict[str, dict[str, Any]] | None = None,
    mechanism_definitions: dict[str, dict[str, Any]] | None = None,
) -> str:
    ability = str(mechanism.get("能力") or "")
    executor = _executor(ability, ability_definitions)
    if executor == "引用机制":
        mechanism_id = str(mechanism.get("机制") or "")
        if not mechanism_definitions or mechanism_id not in mechanism_definitions:
            return f"引用{mechanism_id or '未知机制'}"
        return _mechanism_text(
            dict(mechanism_definitions[mechanism_id]),
            multiplier,
            attribute_definitions,
            include_trigger=include_trigger,
            ability_definitions=ability_definitions,
            mechanism_definitions=mechanism_definitions,
        )
    if executor == "监听事件":
        effects = "；".join(
            _mechanism_text(
                dict(effect),
                multiplier,
                attribute_definitions,
                ability_definitions=ability_definitions,
                mechanism_definitions=mechanism_definitions,
            )
            for effect in mechanism.get("效果") or ()
        )
        conditions = _conditions_text(mechanism.get("条件") or (), ability_definitions)
        body = f"{conditions}，{effects}" if conditions else effects
        return f"{mechanism.get('事件')}，{body}" if include_trigger else body
    if executor == "顺序执行":
        return "；".join(
            _mechanism_text(
                dict(effect),
                multiplier,
                attribute_definitions,
                ability_definitions=ability_definitions,
                mechanism_definitions=mechanism_definitions,
            )
            for effect in mechanism.get("效果") or ()
        )
    if executor == "随机执行":
        options = "；".join(
            _mechanism_text(
                dict(effect),
                multiplier,
                attribute_definitions,
                ability_definitions=ability_definitions,
                mechanism_definitions=mechanism_definitions,
            )
            for effect in mechanism.get("选项") or ()
        )
        return f"随机执行{int(mechanism.get('抽取数量') or 1)}项：{options}"
    if executor == "条件执行":
        conditions = _conditions_text(mechanism.get("条件") or (), ability_definitions)
        effects = "；".join(
            _mechanism_text(
                dict(effect),
                multiplier,
                attribute_definitions,
                ability_definitions=ability_definitions,
                mechanism_definitions=mechanism_definitions,
            )
            for effect in mechanism.get("成立效果") or ()
        )
        return f"{conditions}，{effects}" if conditions else effects
    if executor == "造成伤害":
        name = str(mechanism.get("名称") or "")
        value = _combat_value_text(mechanism.get("数值"), multiplier)
        defense = str(mechanism.get("防御规则") or "普通")
        text = f"{name + '造成' if name else '造成'}{value}伤害"
        return text if defense == "普通" else f"{text}，{defense}"
    if executor == "添加状态":
        status = dict(mechanism.get("状态") or {})
        parts = [
            f"施加{status.get('名称') or '状态'}",
            f"持续{int(status.get('持续数值') or 1)}次行动",
        ]
        for trigger in status.get("触发") or ():
            if trigger.get("事件") != "行动开始":
                continue
            for effect in trigger.get("效果") or ():
                if _executor(str(effect.get("能力") or ""), ability_definitions) == "造成伤害":
                    parts.append(
                        "每次行动"
                        + _mechanism_text(
                            dict(effect),
                            multiplier,
                            attribute_definitions,
                            ability_definitions=ability_definitions,
                            mechanism_definitions=mechanism_definitions,
                        )
                    )
        for key, value in dict(status.get("属性") or {}).items():
            parts.append(
                _attribute_value(
                    str(key),
                    float(value) * multiplier,
                    attribute_definitions,
                )
            )
        if status.get("行动限制"):
            parts.append("限制" + "、".join(str(value) for value in status["行动限制"]))
        if status.get("效果免疫"):
            parts.append("免疫" + "、".join(str(value) for value in status["效果免疫"]))
        if int(status.get("层数上限") or 1) > 1:
            parts.append(f"最多{int(status['层数上限'])}层")
        return "，".join(parts)
    if executor == "恢复资源":
        resource = str(mechanism.get("资源") or "资源")
        return f"恢复{_combat_value_text(mechanism.get('数值'), multiplier)}{resource}"
    if executor == "消耗资源":
        resource = str(mechanism.get("资源") or "资源")
        return f"消耗{_combat_value_text(mechanism.get('数值'), multiplier)}{resource}"
    if executor == "设置资源":
        resource = str(mechanism.get("资源") or "资源")
        return f"将{resource}设为{_combat_value_text(mechanism.get('数值'), multiplier)}"
    if executor == "转移资源":
        source_resource = str(mechanism.get("来源资源") or "资源")
        target_resource = str(mechanism.get("接收资源") or source_resource)
        return f"转移{_combat_value_text(mechanism.get('数值'), multiplier)}{source_resource}为{target_resource}"
    if executor == "移除状态":
        target = str(mechanism.get("状态") or mechanism.get("分类") or "状态")
        quantity = "全部" if mechanism.get("选择全部") else str(int(mechanism.get("数量") or 1))
        return f"移除{quantity}个{target}状态"
    if executor == "修改状态层数":
        action = "增加" if mechanism.get("能力") == "增加状态层数" else "消耗"
        return f"{action}{int(mechanism.get('层数') or 1)}层{mechanism.get('状态') or '状态'}"
    if executor == "修改状态持续":
        action = "延长" if mechanism.get("能力") == "延长状态" else "缩短"
        return f"{action}{mechanism.get('状态') or '状态'}{int(mechanism.get('持续数值') or 1)}次行动"
    if executor in {"复制状态", "转移状态"}:
        action = "复制" if executor == "复制状态" else "转移"
        target = str(mechanism.get("状态") or mechanism.get("分类") or "状态")
        return f"{action}{target}状态"
    if executor == "修改行动条":
        return f"行动准备{mechanism.get('方式') or '增加'}{_number(float(mechanism.get('数值') or 0) * multiplier)}%"
    if executor == "修改技能冷却":
        mode = str(mechanism.get("方式") or "减少")
        amount = int(mechanism.get("数值") or 0)
        selector = dict(mechanism.get("技能") or {})
        quantity = int(selector.get("数量") or 1)
        if selector.get("选择全部"):
            target = "全部冷却中功法"
        elif selector.get("排序") == "随机":
            target = f"随机{quantity}门冷却中功法"
        else:
            target = f"{quantity}门冷却中功法"
        return f"{target}清空冷却" if mode == "清空" else f"{target}{mode}{amount}回合冷却"
    if executor == "修改机制计量":
        counter = str(mechanism.get("计量") or "机制计量")
        mode = str(mechanism.get("方式") or "增加")
        if mode == "清空":
            return f"清空{counter}"
        amount = _combat_value_text(mechanism.get("数值", 0), multiplier)
        return f"{counter}{mode}{amount}"
    if executor == "追加攻击":
        power = _number(float(mechanism.get("威力倍率", 1)) * multiplier * 100)
        return f"追加一次{power}%威力普通攻击"
    if executor == "分摊伤害":
        ratio = _number(float(mechanism.get("比例") or 0) * multiplier)
        return f"替同阵修士分摊{ratio}%待结算伤害"
    if executor == "转移伤害":
        amount = _combat_value_text(mechanism.get("数值"), multiplier)
        return f"替同阵修士承受{amount}待结算伤害"
    if executor == "抵挡致命伤害":
        health = _number(float(mechanism.get("保留血气") or 1))
        return f"抵挡致命伤害并保留{health}点血气"
    if executor == "复活":
        return f"复起并恢复{_number(float(mechanism.get('血气百分比') or 100) * multiplier)}%血气"
    raise ValueError(f"战斗核心未定义执行器展示：{executor or '<空>'}")


def _combat_value_text(value: Any, multiplier: float) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{_number(float(value) * multiplier)}点"
    spec = dict(value or {})
    ability = str(spec.get("能力") or "读取数值")
    if ability == "计算数值":
        left = _combat_value_text(spec.get("左值"), multiplier)
        right = _combat_value_text(spec.get("右值"), multiplier)
        symbols = {
            "相加": "+",
            "相减": "-",
            "相乘": "×",
            "相除": "÷",
            "取最小": "与其取较小值",
            "取最大": "与其取较大值",
            "平均": "与其取平均值",
        }
        return f"({left}{symbols.get(str(spec.get('方式') or '相加'), '+')}{right})"
    if ability == "随机数值":
        low = _combat_value_text(spec.get("最低值"), multiplier)
        high = _combat_value_text(spec.get("最高值"), multiplier)
        return f"{low}至{high}"
    source = str(spec.get("来源") or "固定值")
    percentage = float(spec.get("百分比", 100)) * multiplier
    if source == "固定值":
        amount = float(spec.get("固定值") or 0) * percentage / 100
        return f"{_number(amount)}点"
    source_names = {
        "自身属性": str(spec.get("属性") or "自身属性"),
        "效果来源属性": f"效果来源{spec.get('属性') or '属性'}",
        "目标属性": f"目标{spec.get('属性') or '属性'}",
        "本次伤害": "本次实际伤害",
        "自身当前血气": "当前血气",
        "自身已损失血气": "已损失血气",
        "自身当前精神": "当前精神",
        "自身已损失精神": "已损失精神",
        "自身当前护盾": "当前护盾",
        "目标当前血气": "目标当前血气",
        "目标已损失血气": "目标已损失血气",
        "目标当前精神": "目标当前精神",
        "目标已损失精神": "目标已损失精神",
        "目标当前护盾": "目标当前护盾",
        "本次恢复": "本次实际恢复",
        "本次护盾": "本次获得护盾",
        "本次资源消耗": "本次资源消耗",
        "状态层数": f"{spec.get('状态') or '状态'}层数",
        "机制计量": str(spec.get("计量") or "机制计量"),
    }
    name = source_names.get(source, source)
    result = f"{name}×{percentage / 100:.2f}"
    if "最低值" in spec:
        result += f"，至少{_number(float(spec['最低值']) * multiplier)}点"
    if "最高值" in spec:
        result += f"，至多{_number(float(spec['最高值']) * multiplier)}点"
    return result


def _conditions_text(
    conditions: Any,
    ability_definitions: dict[str, dict[str, Any]] | None = None,
) -> str:
    values: list[str] = []
    for condition in conditions:
        executor = _executor(str(condition.get("能力") or ""), ability_definitions)
        if executor == "概率条件":
            values.append(f"{_number(float(condition.get('概率') or 0))}%概率")
        elif executor == "标签条件":
            tags = "、".join(str(value) for value in condition.get("标签") or ())
            relation = str(condition.get("关系") or "包含全部")
            if relation == "包含任一":
                values.append(f"伤害含任一标签：{tags}")
            elif relation == "全部不含":
                values.append(f"伤害不含标签：{tags}")
            else:
                values.append(f"伤害含标签：{tags}")
        elif executor == "数值条件":
            left = _combat_value_text(condition.get("左值"), 1.0)
            right = _combat_value_text(condition.get("右值"), 1.0)
            values.append(f"{left}{condition.get('比较') or '等于'}{right}")
        elif executor == "状态条件":
            relation = str(condition.get("比较") or "存在")
            suffix = f"{int(condition.get('层数') or 1)}层" if relation.startswith("层数") else ""
            values.append(f"{condition.get('状态') or '状态'}{relation}{suffix}")
        elif executor == "类型条件":
            values.append(f"{condition.get('类型') or '类型'}为{condition.get('值') or '指定值'}")
        elif executor == "组合条件":
            nested = _conditions_text(condition.get("条件") or (), ability_definitions)
            relation = str(condition.get("关系") or "全部成立")
            values.append(f"{relation}：{nested}")
    return "且".join(values)


def _append_effects(
    reply,
    node: dict[str, Any],
    multiplier: float,
    attribute_definitions: dict[str, dict[str, Any]],
    ability_definitions: dict[str, dict[str, Any]],
    mechanism_definitions: dict[str, dict[str, Any]],
) -> None:
    for effect in node.get("效果") or ():
        value = dict(effect)
        executor = _executor(str(value.get("能力") or ""), ability_definitions)
        if executor == "引用机制":
            label = str(value.get("机制") or "机制")
        else:
            label = str(value.get("名称") or value.get("能力") or "效果")
        reply.line(
            f"{label}：",
            _mechanism_text(
                value,
                multiplier,
                attribute_definitions,
                ability_definitions=ability_definitions,
                mechanism_definitions=mechanism_definitions,
            ),
        )


def _executor(
    ability: str,
    definitions: dict[str, dict[str, Any]] | None,
) -> str:
    if definitions and ability in definitions:
        return str(definitions[ability].get("执行器") or ability)
    return ability


def _attribute_value(
    attribute: str,
    value: float,
    attribute_definitions: dict[str, dict[str, Any]],
) -> str:
    if attribute_definitions.get(attribute, {}).get("显示") == "百分比":
        return f"{attribute}+{_number(value)}%"
    return f"{attribute}+{_number(value)}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0")


def _error(line: str):
    return M.document().section("命令未完成", icon="notice").line(line).build()


__all__ = ["handle"]
