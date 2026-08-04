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
from game.core.combat.models import BattleContext, Fighter
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
) -> CombatantSpec:
    return CombatantSpec(
        id=identity,
        name=identity,
        build=build,
        attributes={
            "血气上限": 100,
            "精神上限": 20,
            "攻击": 20,
            "防御": 5,
            "速度": 100,
            "命中率": 100,
        },
    )
