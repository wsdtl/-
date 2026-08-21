from __future__ import annotations

import asyncio
from pathlib import Path

from game.core.asset import AssetService
from game.core.combat import (
    CombatantSpec,
    CombatMedicineSpec,
    CombatRequest,
    CombatService,
)
from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.formation import FormationService
from game.core.location import LocationService
from game.core.world import WorldService
from tests.support import innate_treasure_service


def test_defeated_combatant_loses_all_spirit(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    world = WorldService(data)
    world.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    formation = FormationService(data, database, asset, world, location, innate_treasure_service(data, database))
    formation.initialize()
    combat = CombatService(data, formation)
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


def test_auto_medicine_uses_json_declared_gap_first_order(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    world = WorldService(data)
    world.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    formation = FormationService(data, database, asset, world, location, innate_treasure_service(data, database))
    formation.initialize()
    combat = CombatService(data, formation)
    combat.initialize()
    result = asyncio.run(
        combat.execute(
            CombatRequest(
                left_team=(
                    CombatantSpec(
                        id="left",
                        name="左方",
                        attributes={
                            "血气上限": 100,
                            "精神上限": 100,
                            "攻击": 10,
                            "防御": 0,
                            "速度": 100,
                            "命中率": 100,
                        },
                        health=82,
                        spirit=100,
                        inventory={"small": 1, "fit": 1, "large": 1},
                        inventory_owner_id="qq-1",
                        auto_medicine=True,
                        medicine_threshold=0.9,
                    ),
                ),
                right_team=(
                    CombatantSpec(
                        id="right",
                        name="右方",
                        attributes={
                            "血气上限": 100,
                            "精神上限": 100,
                            "攻击": 1,
                            "防御": 0,
                            "速度": 1,
                            "命中率": 100,
                        },
                    ),
                ),
                seed=1,
                action_limit=1,
                medicine_definitions=(
                    CombatMedicineSpec("small", "100001", "01", "血气", 10, 1),
                    CombatMedicineSpec("fit", "100002", "02", "血气", 20, 2),
                    CombatMedicineSpec("large", "100003", "03", "血气", 25, 3),
                ),
                medicine_selection_strategy="缺口优先",
            )
        )
    )

    left = result.left_results[0]
    assert left.consumed_items == {"fit": 1}
    assert left.health == 100
