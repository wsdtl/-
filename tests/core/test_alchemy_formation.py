from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.alchemy import AlchemyService
from game.core.asset import AssetService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, TransactionCommand
from game.core.formation import FormationService, FormationUnavailableError
from game.core.location import LocationService
from game.core.world import LocationQuery, WorldService
from tests.support import innate_treasure_service


def _run(awaitable):
    return asyncio.run(awaitable)


def _services(tmp_path: Path):
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
    alchemy = AlchemyService(data, database, asset, world, location, innate_treasure_service(data, database))
    alchemy.initialize()
    formation = FormationService(data, database, asset, world, location, innate_treasure_service(data, database))
    formation.initialize()
    return data, world, database, location, asset, alchemy, formation


def _seed_materials(
    data: JsonDataService,
    world: WorldService,
    database: DatabaseService,
    location: LocationService,
    asset: AssetService,
) -> None:
    by_category: dict[str, list[str]] = {"兽宝": [], "灵矿": [], "灵植": []}
    for item_id in data.entities("物品"):
        category = data.entity_record("物品", item_id).number_category
        if category in by_category:
            by_category[category].append(item_id)
    items = [
        (min(by_category["兽宝"]), "05", 100),
        (min(by_category["灵矿"]), "05", 100),
        *((item_id, "05", 20) for item_id in sorted(by_category["灵植"])),
    ]
    destination = world.locate(LocationQuery(location_name="镜湖城"))
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "seed-materials",
                "测试准备材料",
                (
                    location.initial_mutation("qq-1", destination.xy),
                    *asset.initial_inventory_mutations("qq-1", items),
                ),
                {},
            )
        )
    )


def test_alchemy_refines_once_and_replays_without_reconsuming(tmp_path: Path) -> None:
    data, world, database, location, asset, alchemy, _ = _services(tmp_path)
    try:
        _seed_materials(data, world, database, location, asset)
        status = alchemy.status()
        assert status.recipe_count == 359
        assert status.medicine_count == 359
        assert status.alchemist_count == 8

        overview = _run(alchemy.overview("qq-1"))
        assert sum(count for _, count in overview.category_counts) == 359
        category = overview.category_counts[0][0]
        recipe = _run(alchemy.list_recipes("qq-1", category)).entries[0].recipe
        preview = _run(alchemy.preview("qq-1", recipe.recipe_id))
        assert preview.can_refine is True
        assert preview.medicine_grade_id == "04"
        assert preview.medicine_grade_name == "天品"
        assert preview.beast_material is not None
        assert len({item.item_id for item in preview.herb_materials}) == len(
            preview.herb_materials
        )

        result = _run(alchemy.refine("qq-1", "refine-1", recipe.recipe_id))
        replay = _run(alchemy.refine("qq-1", "refine-1", recipe.recipe_id))
        assert result.quantity_after == result.quantity_before + 1
        assert replay.replayed is True
        assert replay.quantity_after == result.quantity_after
    finally:
        database.close()


def test_formation_forms_arms_and_consumes_prepared_state(tmp_path: Path) -> None:
    data, world, database, location, asset, _, formation = _services(tmp_path)
    try:
        _seed_materials(data, world, database, location, asset)
        status = formation.status()
        assert status.formation_count == 46
        assert status.master_count == 8
        assert status.fixed_grade_count == 4
        assert status.unlimited_grade == "圣"

        entry = _run(formation.overview("qq-1")).entries[0]
        with pytest.raises(FormationUnavailableError, match="最高支持天品"):
            _run(formation.preview("qq-1", entry.formation.formation_id, "圣"))
        preview = _run(
            formation.preview("qq-1", entry.formation.formation_id, "黄")
        )
        assert preview.can_form is True
        result = _run(
            formation.form(
                "qq-1", "form-1", entry.formation.formation_id, preview.grade_name
            )
        )
        replay = _run(
            formation.form(
                "qq-1", "form-1", entry.formation.formation_id, preview.grade_name
            )
        )
        assert result.quantity_after == result.quantity_before + 1
        assert replay.replayed is True

        armed = _run(formation.arm("qq-1", "arm-1", result.reserve_key))
        activation = _run(formation.activation_plan("qq-1"))
        assert activation is not None
        assert activation.prepared == armed.prepared
        assert activation.profile.formation_id == entry.formation.formation_id
        _run(
            database.commit(
                TransactionCommand(
                    "qq-1",
                    "battle-1",
                    "正式战斗建立",
                    (activation.operation,),
                    {},
                )
            )
        )
        assert _run(formation.prepared("qq-1")) is None
    finally:
        database.close()
