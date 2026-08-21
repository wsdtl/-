from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from game.core.asset import AssetService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, StateAddress, TransactionCommand
from game.core.forging import ForgingMaterialError, ForgingService
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
    forging = ForgingService(data, database, asset, world, location, innate_treasure_service(data, database))
    forging.initialize()
    return data, world, database, location, asset, forging


def _seed(
    world: WorldService,
    database: DatabaseService,
    location: LocationService,
    asset: AssetService,
    items: Sequence[tuple[str, str, int]],
    *,
    user_id: str = "qq-1",
) -> None:
    xy = world.locate(LocationQuery(location_name="天衡城")).xy
    operations = (
        location.initial_mutation(user_id, xy),
    ) + asset.initial_inventory_mutations(user_id, items)
    _run(
        database.commit(TransactionCommand(user_id, "seed", "测试准备", operations, {}))
    )


def _rules(data: JsonDataService, name: str) -> tuple[Mapping[str, object], ...]:
    value = data.dataset("炼器规则").get(name)
    assert isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    assert all(isinstance(row, Mapping) for row in value)
    return tuple(value)  # type: ignore[arg-type]


def _beasts(data: JsonDataService, trait: str, count: int) -> tuple[str, ...]:
    values: list[str] = []
    for row in _rules(data, "归引"):
        if row.get("兽脉") == trait:
            values.extend(data.pool_members((str(row["兽宝池"]),), "物品"))
    assert len(set(values)) >= count
    return tuple(sorted(set(values))[:count])


def _minerals(
    data: JsonDataService,
    trait: str,
    count: int,
    *,
    relation: str = "本脉",
    excluded: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    values: list[str] = []
    for row in _rules(data, "归脉"):
        if row.get(relation) == trait:
            values.extend(data.pool_members((str(row["灵矿池"]),), "物品"))
    candidates = tuple(sorted(set(values) - set(excluded)))
    assert len(candidates) >= count
    return candidates[:count]


def test_forging_owns_complete_static_contract_and_weapon_rules(tmp_path: Path) -> None:
    _, _, _, _, _, forging = _services(tmp_path)

    status = forging.status()
    assert (
        status.law_count,
        status.method_count,
        status.artisan_count,
        status.beast_treasure_count,
        status.mineral_count,
    ) == (64, 32, 25, 366, 108)
    assert forging.initial_weapon_level() == 1
    assert forging.weapon_stage(10).name == "凡器"
    assert forging.weapon_stage(11).open_law_slots == 1
    assert forging.weapon_stage(76).open_law_slots == 4
    assert forging.weapon_attack(1) == 10
    assert forging.weapon_attack(11) == 20
    assert forging.law_allowed(51, "灵器")
    assert not forging.law_allowed(11, "法器")
    advance = forging.advance_weapon(
        level=10,
        experience=forging.weapon_experience_required(10) - 1,
        gained=1,
    )
    assert (advance.level_after, advance.stage_after, advance.open_slots_after) == (
        11,
        "灵器",
        1,
    )


def test_incomplete_materials_create_no_forging_mutation(tmp_path: Path) -> None:
    _, world, database, location, asset, forging = _services(tmp_path)
    _seed(world, database, location, asset, ())

    preview = _run(forging.preview("qq-1", "太白惊鸿"))
    assert not preview.can_forge
    assert preview.missing_materials
    before = database.status().transaction_count
    with pytest.raises(ForgingMaterialError, match="不足"):
        _run(forging.forge("qq-1", "forge-1", "700001"))
    assert database.status().transaction_count == before
    assert _run(database.get(StateAddress("qq-1", "law_reserve", "700001"))) is None


def test_forging_consumes_materials_and_replays_atomically(tmp_path: Path) -> None:
    data, world, database, location, asset, forging = _services(tmp_path)
    beasts = _beasts(data, "岳骨", 1) + _beasts(data, "天风", 1)
    minerals = _minerals(data, "天金", 2) + _minerals(data, "玄铁", 2)
    _seed(
        world,
        database,
        location,
        asset,
        tuple((item_id, "01", 1) for item_id in beasts + minerals),
    )

    preview = _run(forging.preview("qq-1", "700001"))
    assert preview.can_forge
    assert preview.secondary_substitutions == 0
    result = _run(forging.forge("qq-1", "forge-1", "太白惊鸿"))
    assert (result.quantity_before, result.quantity_after, result.replayed) == (
        0,
        1,
        False,
    )
    assert all(
        _run(database.get(StateAddress("qq-1", "inventory", f"{item_id}:01"))) is None
        for item_id in beasts + minerals
    )
    reserve = _run(database.get(StateAddress("qq-1", "law_reserve", "700001")))
    assert reserve is not None and reserve.value["数量"] == 1
    transaction_count = database.status().transaction_count

    replay = _run(forging.forge("qq-1", "forge-1", "700001"))
    assert replay.replayed
    assert (replay.quantity_before, replay.quantity_after) == (0, 1)
    assert database.status().transaction_count == transaction_count


def test_same_mineral_cannot_fill_two_slots_even_with_large_quantity(
    tmp_path: Path,
) -> None:
    data, world, database, location, asset, forging = _services(tmp_path)
    beasts = _beasts(data, "岳骨", 1) + _beasts(data, "天风", 1)
    gold = _minerals(data, "天金", 1)
    iron = _minerals(data, "玄铁", 2)
    items = tuple((item_id, "01", 1) for item_id in beasts + iron) + (
        (gold[0], "01", 99),
    )
    _seed(world, database, location, asset, items)

    preview = _run(forging.preview("qq-1", "700001"))
    assert not preview.can_forge
    assert sum(material.trait == "天金" for material in preview.mineral_materials) == 1
    assert any(
        missing.category == "灵矿" and missing.trait == "天金"
        for missing in preview.missing_materials
    )


def test_matching_reassigns_flexible_mineral_and_uses_two_for_secondary(
    tmp_path: Path,
) -> None:
    data, world, database, location, asset, forging = _services(tmp_path)
    beasts = _beasts(data, "岳骨", 1) + _beasts(data, "天风", 1)
    flexible = next(
        item_id
        for row in _rules(data, "归脉")
        if row.get("本脉") == "天金" and row.get("旁脉") == "玄铁"
        for item_id in data.pool_members((str(row["灵矿池"]),), "物品")
    )
    other_gold = _minerals(data, "天金", 2, excluded=frozenset({flexible}))
    iron = _minerals(data, "玄铁", 1)
    items = tuple((item_id, "01", 1) for item_id in beasts + other_gold + iron) + (
        (flexible, "01", 2),
        (other_gold[0], "02", 1),
    )
    _seed(world, database, location, asset, items)

    preview = _run(forging.preview("qq-1", "700001"))
    assert preview.can_forge
    assert preview.secondary_substitutions == 1
    secondary = next(
        material
        for material in preview.mineral_materials
        if material.relation == "旁脉"
    )
    assert (secondary.item_id, secondary.trait, secondary.quantity) == (
        flexible,
        "玄铁",
        2,
    )
    chosen_gold = next(
        material
        for material in preview.mineral_materials
        if material.item_id == other_gold[0]
    )
    assert chosen_gold.grade_id == "01"
