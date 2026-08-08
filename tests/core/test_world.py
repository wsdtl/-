from __future__ import annotations

from pathlib import Path

import pytest

from game.core.data import JsonDataError, JsonDataService
from game.core.world import JourneyQuery, LocationQuery, WorldService
from game.core.world.service import _validate_location_data


@pytest.fixture(scope="module")
def world() -> WorldService:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    service = WorldService(data)
    service.initialize()
    return service


def test_world_initialization_builds_one_complete_map_contract(
    world: WorldService,
) -> None:
    status = world.status()
    view = world.map_view()

    assert status.initialized is True
    assert (
        status.location_count,
        status.region_count,
        status.road_count,
        status.terrain_cell_count,
    ) == (81, 11, 118, 10_000)
    assert view.schema == "game.world_map.presentation"
    assert view.version == 2
    assert view.name == "晓楠修仙界"
    assert view.birthplace_key == view.birthplace == "溪隐台"
    assert view.bounds == (0, 99, 0, 99)
    assert view.cell_size_meters == 10_000
    assert view.altitude_range == (-33333, 28710)
    assert len(view.surface) == 100
    assert all(len(row) == 100 for row in view.surface)
    assert len(view.terrain_zones) == 85
    assert status.journey_realm_count == 20
    assert sum(region.cell_count for region in view.regions) == 10_000
    assert sum(zone.cell_count for zone in view.terrain_zones) == 10_000


def test_journey_plan_exposes_route_metrics_passages_and_realm_narrative(
    world: WorldService,
) -> None:
    plan = world.plan_journey(
        JourneyQuery(
            origin_xy=(15, 17),
            destination=LocationQuery(location_name="天衡城"),
            realm_id="510001",
        )
    )

    assert plan.origin.location_name == "溪隐台"
    assert plan.destination.location_name == "天衡城"
    assert plan.route[0] == (15, 17)
    assert plan.route[-1] == plan.destination.xy
    assert plan.realm_name == "灵动"
    assert plan.travel_method == "引息轻行"
    assert plan.metrics.horizontal_distance_m > 0
    assert plan.metrics.weighted_distance_m > plan.metrics.horizontal_distance_m
    assert plan.metrics.road_segment_count == sum(
        segment.kind == "道路" for segment in plan.passages
    )
    assert plan.metrics.terrain_segment_count == sum(
        segment.kind == "地形" for segment in plan.passages
    )
    rendered = "\n".join(plan.narrative)
    assert "你调匀初生灵息" in rendered
    assert "灵息在血肉间缓缓往复" in rendered
    assert "落脚天衡城" in rendered


def test_all_realms_have_distinct_data_driven_journey_identity(
    world: WorldService,
) -> None:
    plans = tuple(
        world.plan_journey(
            JourneyQuery(
                origin_xy=(15, 17),
                destination=LocationQuery(xy=(16, 17)),
                realm_id=f"510{index:03d}",
            )
        )
        for index in range(1, 21)
    )

    assert len({plan.travel_method for plan in plans}) == 20
    assert len({plan.narrative[0] for plan in plans}) == 20
    assert len({plan.narrative[-2] for plan in plans}) == 20


def test_location_name_xy_and_map_view_resolve_the_same_world_fact(
    world: WorldService,
) -> None:
    by_name = world.locate(LocationQuery(location_name="溪隐台"))
    by_xy = world.locate(LocationQuery(xy=(15, 17)))
    mapped = next(item for item in world.map_view().locations if item.name == "溪隐台")

    assert by_name == by_xy
    assert mapped.key == by_name.location_key == "溪隐台"
    assert mapped.xy == by_name.xy == (15, 17)
    assert mapped.region == by_name.region == "青岚州"
    assert mapped.terrain == by_name.terrain == "溪谷"
    assert mapped.altitude == by_name.altitude
    assert mapped.available_functions == by_name.available_functions


def test_location_json_identity_and_feature_fields_are_strict() -> None:
    base = {"坐标": [8, 8], "说明": "溪隐台", "可用功能": ["闭关"]}
    requirements = {"闭关": ((), ())}

    for field in ("地点类别", "行政层级", "形制", "显示名称"):
        with pytest.raises(JsonDataError, match="身份和层级必须由目录表达"):
            _validate_location_data(
                {**base, field: "重复身份"},
                "溪隐台",
                requirements,
            )

    with pytest.raises(JsonDataError, match="字段没有对应功能要求"):
        _validate_location_data(
            {**base, "单次遭遇敌人数": [1, 2]},
            "溪隐台",
            requirements,
        )
    with pytest.raises(JsonDataError, match="单次遭遇敌人数"):
        _validate_location_data(
            {"坐标": [8, 8], "说明": "溪隐台", "可用功能": ["探险"]},
            "溪隐台",
            {"探险": ((), ("单次遭遇敌人数",))},
        )
