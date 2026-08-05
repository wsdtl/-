"""战斗运行期索引与异步边界回归测试。"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

from game.core.combat import (
    CombatantSpec,
    CombatBuildRef,
    CombatFormationSpec,
    CombatReportSpec,
    CombatRequest,
    CombatService,
)
from game.core.combat.models import BattleContext, EventFrame, Fighter, StatusState
from game.core.data import JsonDataService


def test_battle_context_updates_fighter_indexes_for_summons() -> None:
    left = _fighter("left")
    right = _fighter("right")
    context = BattleContext(
        rng=random.Random(1),
        left=left,
        right=right,
        medicine_definitions={},
    )
    summon = _fighter("summon")
    summon.side = 0

    context.add_fighter(summon)

    assert context.fighter_by_id("summon") is summon
    assert context.fighters == (left, summon, right)
    assert context.fighter_order == {"left": 0, "summon": 1, "right": 2}
    assert context.listener_index_dirty is True


def test_async_team_battle_preserves_seeded_result() -> None:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    combat = CombatService(data)
    combat.initialize()
    technique_id = next(iter(data.entities("功法")))
    request = CombatRequest(
        left_team=(
            _combatant(
                "left",
                build=(CombatBuildRef("功法", technique_id, born_order=1),),
            ),
        ),
        right_team=(_combatant("right"),),
        seed=17,
        action_limit=100,
        report=CombatReportSpec(
            generated_at="2026-08-02T00:00:00+08:00",
            include_presentation=True,
        ),
    )

    direct = combat._execute_sync(request)
    asynchronous = asyncio.run(combat.execute(request))

    assert asynchronous == direct
    assert asynchronous.report is not None
    assert asynchronous.presentation is not None


def test_formations_are_battlefield_objects_with_saint_material_scaling() -> None:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    combat = CombatService(data)
    status = combat.initialize()
    assert status.formation_count == 46
    request = CombatRequest(
        left_team=(_combatant("left"),),
        right_team=(_combatant("right"),),
        seed=1,
        action_limit=30,
        left_formation=CombatFormationSpec("530001", "圣", materials={"兽宝": 1944, "灵矿": 5832, "灵植": 3888}),
        right_formation=CombatFormationSpec("530002"),
    )

    result = combat._execute_sync(request)

    assert [value.side for value in result.formations] == [0, 1]
    assert result.formations[0].grade == "圣"
    assert result.formations[0].capacity > 0
    assert result.formations[0].rotations > 0


def test_formation_nodes_split_total_impact_across_multiple_combatants() -> None:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    combat = CombatService(data)
    combat.initialize()
    request = CombatRequest(
        left_team=(_combatant("left", attack=1, health_max=10_000),),
        right_team=(
            _combatant("right-1", attack=1, health_max=10_000),
            _combatant("right-2", attack=1, health_max=10_000),
        ),
        seed=3,
        action_limit=20,
        left_formation=CombatFormationSpec("530001"),
    )

    result = combat._execute_sync(request)

    impacts = [
        event
        for event in result.events
        if event.kind == "阵法冲击后" and event.values.get("是否命中阵法") is False
    ]
    assert impacts
    first_rotation = impacts[:2]
    assert {event.target_id for event in first_rotation} == {"right-1", "right-2"}
    assert sum(event.amount for event in first_rotation) == 900
    assert {event.values["覆盖目标数"] for event in first_rotation} == {2}


def test_any_target_scope_and_status_copy_execute_in_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    combat = CombatService(data)
    combat.initialize()
    engine = combat._require_engine()
    source = _fighter("source")
    ally = _fighter("ally")
    target = _fighter("target")
    source.side = ally.side = 0
    target.side = 1
    context = BattleContext(
        rng=random.Random(7),
        left=source,
        right=target,
        medicine_definitions={},
    )
    context.add_fighter(ally)

    selected = engine._select_targets(
        context,
        source,
        target,
        {"能力": "选择目标", "范围": "任意", "排除自身": True, "选择全部": True},
    )
    assert {value.id for value in selected} == {"ally", "target"}

    source.statuses.append(StatusState(name="无垢", category="正面"))
    copied = engine._mechanism_copy_status(
        context,
        source,
        target,
        {
            "状态": {
                "能力": "选择状态",
                "目标": {"能力": "选择目标", "范围": "自身"},
                "名称": "无垢",
            },
            "接收目标": {
                "能力": "选择目标",
                "范围": "己方",
                "排除自身": True,
            },
        },
        1,
    )
    assert copied is True
    assert [status.name for status in ally.statuses] == ["无垢"]


def test_fatal_damage_can_be_transferred_to_an_ally() -> None:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    combat = CombatService(data)
    combat.initialize()
    engine = combat._require_engine()
    target = _fighter("target")
    ally = _fighter("ally")
    source = _fighter("source")
    target.side = ally.side = 0
    source.side = 1
    target.health = 50
    context = BattleContext(
        rng=random.Random(9),
        left=target,
        right=source,
        medicine_definitions={},
    )
    context.add_fighter(ally)
    fatal = EventFrame(
        kind="受到致命伤害",
        source=source,
        target=target,
        facts={"当前数值": 100},
    )
    context.event_stack.append(fatal)

    changed = engine._mechanism_transfer_damage(
        context,
        target,
        source,
        {
            "目标": {
                "能力": "选择目标",
                "范围": "己方",
                "排除自身": True,
            },
            "数值": 30,
        },
        1,
    )

    assert changed is True
    assert fatal.cancelled is True
    assert fatal.facts["保留血气"] == 1
    assert ally.health == 70


def _fighter(identity: str) -> Fighter:
    return Fighter(
        id=identity,
        name=identity,
        attributes={"血气上限": 100, "精神上限": 20, "攻击": 10, "速度": 100},
        health=100,
        spirit=20,
    )


def _combatant(
    identity: str,
    *,
    build: tuple[CombatBuildRef, ...] = (),
    attack: float = 20,
    health_max: float = 100,
) -> CombatantSpec:
    return CombatantSpec(
        id=identity,
        name=identity,
        build=build,
        attributes={
            "血气上限": health_max,
            "精神上限": 20,
            "攻击": attack,
            "防御": 5,
            "速度": 100,
            "命中率": 100,
        },
    )
