"""世界、行程、物品与炼药微服务的公共行为。"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

import game.app as game_app
from game.core.alchemy import (
    DIRECT_MODE,
    SIDE_MODE,
    AlchemyError,
    AlchemyMaterial,
    AlchemyRequest,
    AlchemyService,
)
from game.core.build import BuildRequest, BuildService, BuildSlotRequest
from game.core.data import JsonDataService
from game.core.item import ItemService
from game.core.pool import PoolService
from game.core.role import RoleService
from game.core.travel import TravelRequest, TravelService
from game.core.world import SurfaceCoordinate, WorldService


def test_world_derives_location_altitude_from_xy() -> None:
    _, world, _, _, _ = _services()

    birthplace = world.birthplace()
    assert birthplace.identity == "青溪村"
    assert birthplace.coordinate == SurfaceCoordinate(8, 8)
    assert birthplace.altitude == world.altitude(birthplace.coordinate) == 2360
    assert world.location((8, 8)) == birthplace
    assert world.location(SurfaceCoordinate(8, 8)) == birthplace
    assert world.location_at(8, 8) == birthplace
    assert world.status().location_count == 80
    assert world.status().road_count == 113
    assert {value.name for value in world.features()} == {"闭关", "修士", "探险"}
    assert birthplace.plant_pools == ("灵植-溪谷",)
    assert birthplace.mineral_pools == ("灵矿-溪谷",)


def test_locations_and_enemies_reference_both_local_resource_pools() -> None:
    data, world, _, _, _ = _services()

    for location in world.locations():
        expected_minerals = tuple(
            pool.replace("灵植-", "灵矿-", 1) for pool in location.plant_pools
        )
        assert location.plant_pools
        assert location.mineral_pools == expected_minerals
        for enemy_id in data.pool_members(location.enemy_pools, "敌人"):
            item_pools = set(data.entity("敌人", enemy_id)["掉落"]["物品池"])
            assert set(location.plant_pools) <= item_pools
            assert set(location.mineral_pools) <= item_pools


def test_travel_builds_a_connected_route_and_json_narrative() -> None:
    _, world, travel, _, _ = _services()

    plan = travel.plan(TravelRequest(start="青溪村", destination="裂天原"))

    assert plan.points[0].coordinate == world.location("青溪村").coordinate
    assert plan.points[-1].coordinate == world.location("裂天原").coordinate
    assert plan.metrics.road_segments == len(plan.road_types)
    assert plan.metrics.total_ascent > 0
    assert plan.metrics.total_descent > 0
    assert "你离开青溪村" in plan.narrative
    assert "抵达裂天原" in plan.narrative

    coordinate_plan = travel.plan(
        TravelRequest(
            start=(8, 8),
            destination=world.location("裂天原").coordinate,
        )
    )
    assert coordinate_plan.start == "青溪村"
    assert coordinate_plan.destination == "裂天原"
    assert coordinate_plan.metrics == plan.metrics
    assert travel.realm_effects().travel_speed is True
    assert travel.realm_effects().destination_reachability is False


def test_item_service_separates_definitions_from_inventory_instances() -> None:
    _, _, _, items, _ = _services()

    recovery = items.item("100001")
    battle_pill = items.item("100127")

    assert recovery.category == "丹药"
    assert recovery.use_effect is not None
    assert recovery.use_effect.recovery_percent == 6
    assert battle_pill.use_effect is not None
    assert battle_pill.use_effect.battle_mechanisms == ("600882", "600885")
    assert not hasattr(recovery, "quantity")


def test_alchemy_plans_direct_vein_materials_without_inventory_access() -> None:
    data, _, _, items, alchemy = _services()
    request = _direct_request(data, items, alchemy, "110001")

    plan = alchemy.plan(request)

    assert plan.output_item_id == "100007"
    assert plan.output_count == 1
    assert {value.mode for value in plan.allocations} == {DIRECT_MODE}
    assert plan.grade_basis.guide_grades == (plan.recipe.minimum_guide_grade,)
    assert plan.output_grade == plan.recipe.minimum_guide_grade


def test_alchemy_accepts_one_side_vein_substitution_and_rejects_low_grade() -> None:
    data, _, _, items, alchemy = _services()
    request = _side_request(data, items, alchemy, "110001")

    plan = alchemy.plan(request)
    assert sum(value.mode == SIDE_MODE for value in plan.allocations) == 2

    with pytest.raises(AlchemyError, match="药引品级不足"):
        alchemy.plan(
            AlchemyRequest(
                recipe_id=request.recipe_id,
                guides=(AlchemyMaterial(request.guides[0].item_id, "01"),),
                auxiliaries=request.auxiliaries,
            )
        )


def test_alchemy_output_grade_advances_only_when_every_material_has_margin() -> None:
    data, _, _, items, alchemy = _services()
    request = _direct_request(data, items, alchemy, "110001")
    upgraded = AlchemyRequest(
        recipe_id=request.recipe_id,
        guides=tuple(AlchemyMaterial(value.item_id, "03") for value in request.guides),
        auxiliaries=tuple(
            AlchemyMaterial(value.item_id, "02") for value in request.auxiliaries
        ),
    )

    assert alchemy.plan(upgraded).output_grade == "03"


def test_every_recipe_has_enough_plant_auxiliaries() -> None:
    data, _, _, items, alchemy = _services()

    plans = tuple(
        alchemy.plan(_direct_request(data, items, alchemy, recipe.identity))
        for recipe in alchemy.recipes()
    )

    assert len(plans) == 160
    assert all(plan.allocations for plan in plans)


def test_composition_root_exposes_all_four_domain_services(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        game_app,
        "logger",
        SimpleNamespace(
            opt=lambda **_kwargs: SimpleNamespace(
                success=lambda *_args, **_kwargs: None
            )
        ),
    )

    services = game_app.build_game_services(data_dir=root / "data")

    assert services.core.world.status().location_count == 80
    assert services.core.travel.status().road_count == 113
    assert services.core.item.status().item_count == 748
    assert services.core.alchemy.status().recipe_count == 160
    assert services.core.role.status().companion_count == 264
    assert services.core.build.status().conflict_count == 5


def test_role_and_build_services_form_enemy_combat_inputs() -> None:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    pools = PoolService(data)
    pools.initialize()
    items = ItemService(data)
    items.initialize()
    roles = RoleService(data, items)
    roles.initialize()
    builds = BuildService(data, pools)
    builds.initialize()

    profile = roles.enemy("龙脊鳞蜥", seed=1001)
    result = builds.generate(
        BuildRequest(
            slots=tuple(
                BuildSlotRequest(
                    section=slot.section,
                    count=slot.count,
                    file_ids=slot.file_ids,
                    full_pool=slot.full_pool,
                )
                for slot in profile.build_slots
            ),
            seed=1001,
        )
    )

    assert profile.kind == "灵兽"
    assert profile.level in range(21, 26)
    assert len(result.identities) == 9


def _direct_request(
    data: JsonDataService,
    items: ItemService,
    alchemy: AlchemyService,
    recipe_id: str,
) -> AlchemyRequest:
    recipe = alchemy.recipe(recipe_id)
    furnace = alchemy.furnace_method(recipe.furnace_method)
    pools = _vein_pools(data)
    used: set[str] = set()
    auxiliaries: list[AlchemyMaterial] = []
    for requirement in furnace.requirements:
        for _ in range(requirement.count):
            identity = _unused_material(data, pools[requirement.vein], used)
            used.add(identity)
            auxiliaries.append(
                AlchemyMaterial(identity, recipe.minimum_auxiliary_grade)
            )
    guide = data.pool_members((recipe.guide_pool,), "物品")[0]
    assert items.item(guide).category == "兽宝"
    return AlchemyRequest(
        recipe_id=recipe_id,
        guides=(AlchemyMaterial(guide, recipe.minimum_guide_grade),),
        auxiliaries=tuple(auxiliaries),
    )


def _side_request(
    data: JsonDataService,
    items: ItemService,
    alchemy: AlchemyService,
    recipe_id: str,
) -> AlchemyRequest:
    direct = _direct_request(data, items, alchemy, recipe_id)
    recipe = alchemy.recipe(recipe_id)
    allocations = list(direct.auxiliaries)
    assignments = data.dataset("炼药规则")["归脉"]
    primary_by_pool = {str(row["灵植池"]): str(row["本脉"]) for row in assignments}
    target = alchemy.furnace_method(recipe.furnace_method).requirements[0].vein
    removed = next(
        value
        for value in allocations
        if primary_by_pool[items.item(value.item_id).source_pool] == target
    )
    allocations.remove(removed)
    used = {value.item_id for value in allocations}
    side_pools = [
        str(row["灵植池"])
        for row in assignments
        if row["旁脉"] == target and row["本脉"] != target
    ]
    side_ids = []
    for pool in side_pools:
        for identity in data.pool_members((pool,), "物品"):
            if identity not in used:
                side_ids.append(identity)
            if len(side_ids) == 2:
                break
        if len(side_ids) == 2:
            break
    assert len(side_ids) == 2
    allocations.extend(
        AlchemyMaterial(identity, recipe.minimum_auxiliary_grade)
        for identity in side_ids
    )
    return AlchemyRequest(
        recipe_id=recipe_id,
        guides=direct.guides,
        auxiliaries=tuple(allocations),
    )


def _vein_pools(data: JsonDataService) -> dict[str, list[str]]:
    pools: dict[str, list[str]] = defaultdict(list)
    for row in data.dataset("炼药规则")["归脉"]:
        pools[str(row["本脉"])].append(str(row["灵植池"]))
    return pools


def _unused_material(
    data: JsonDataService,
    pools: list[str],
    used: set[str],
) -> str:
    for pool in pools:
        for identity in data.pool_members((pool,), "物品"):
            if identity not in used:
                return identity
    raise AssertionError("测试数据没有足够的本脉灵植")


@lru_cache(maxsize=1)
def _services() -> tuple[
    JsonDataService,
    WorldService,
    TravelService,
    ItemService,
    AlchemyService,
]:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    world = WorldService(data)
    world.initialize()
    travel = TravelService(data, world)
    travel.initialize()
    items = ItemService(data)
    items.initialize()
    alchemy = AlchemyService(data, items)
    alchemy.initialize()
    return data, world, travel, items, alchemy
