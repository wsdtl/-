from __future__ import annotations

import asyncio
from pathlib import Path

from game.core.combat import CombatantSpec, CombatRequest, CombatService
from game.core.data import JsonDataService


def test_defeated_combatant_loses_all_spirit() -> None:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    combat = CombatService(data)
    combat.initialize()
    result = asyncio.run(
        combat.execute(
            CombatRequest(
                left_team=(
                    CombatantSpec(
                        id="left",
                        name="左方",
                        attributes={
                            "血气上限": 10,
                            "精神上限": 100,
                            "攻击": 1,
                            "防御": 0,
                            "速度": 1,
                            "命中率": 100,
                        },
                        health=10,
                        spirit=100,
                    ),
                ),
                right_team=(
                    CombatantSpec(
                        id="right",
                        name="右方",
                        attributes={
                            "血气上限": 100,
                            "精神上限": 100,
                            "攻击": 1000,
                            "防御": 0,
                            "速度": 100,
                            "命中率": 100,
                        },
                    ),
                ),
                seed=1,
                action_limit=10,
            )
        )
    )

    defeated = result.left_results[0]
    assert defeated.alive is False
    assert defeated.health == 0
    assert defeated.spirit == 0
