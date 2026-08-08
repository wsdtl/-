from __future__ import annotations

from collections import defaultdict, deque
from itertools import pairwise
from pathlib import Path

import pytest

from game.core.data import JsonDataError, JsonDataService
from game.core.world import LocationQuery, WorldService
from game.core.world.service import _validate_location_data


@pytest.fixture(scope="module")
def world() -> WorldService:
    root = Path(__file__).resolve().parents[3]
    data = JsonDataService(root / "data")
    data.initialize()
    service = WorldService(data)
    service.initialize()
    return service


def test_map_view_covers_complete_world_data(world: WorldService) -> None:
    view = world.map_view()

    assert view.schema == "game.world_map.presentation"
    assert view.version == 2
    assert view.name == "晓楠修仙界"
    assert view.birthplace_key == "溪隐台"
    assert view.birthplace == "溪隐台"
    assert view.bounds == (0, 99, 0, 99)
    assert view.cell_size_meters == 10_000
    assert view.altitude_range == (-33333, 28710)
    assert len(view.surface) == 100
    assert all(len(row) == 100 for row in view.surface)
    assert len(view.regions) == 11
    assert len(view.terrain_zones) == 85
    assert len(view.locations) == 81
    assert len(view.roads) == 118
    assert sum(region.cell_count for region in view.regions) == 10_000
    assert sum(zone.cell_count for zone in view.terrain_zones) == 10_000


def test_map_boundary_is_sealed_by_sea_mountains_and_abyss(
    world: WorldService,
) -> None:
    view = world.map_view()

    assert all(view.surface[0][x] < 0 for x in range(100))
    assert all(view.surface[y][0] < 0 for y in range(90))
    assert all(view.surface[y][99] < 0 for y in range(90))
    assert view.surface[0][99] == -33333
    assert min(min(row) for row in view.surface[94:]) >= 12000

    zone_names = {zone.name for zone in view.terrain_zones}
    assert {"东南天渊", "黑石岭", "无光绝岭"} <= zone_names


def test_coastlines_meander_instead_of_forming_uniform_bands(
    world: WorldService,
) -> None:
    surface = world.map_view().surface

    west_runs = tuple(_negative_run(surface[y]) for y in range(5, 91, 5))
    east_runs = tuple(
        _negative_run(tuple(reversed(surface[y]))) for y in range(5, 91, 5)
    )
    south_runs = tuple(
        _negative_run(tuple(surface[y][x] for y in range(100))) for x in range(5, 96, 5)
    )

    for runs in (west_runs, east_runs, south_runs):
        assert len(set(runs)) >= 5
        assert max(runs) - min(runs) >= 4


def test_map_regions_and_terrain_form_connected_world_partitions(
    world: WorldService,
) -> None:
    view = world.map_view()
    regions = view.regions
    south = tuple(region for region in regions if region.category == "州")
    frontier = tuple(region for region in regions if region.category == "防线")
    north = tuple(region for region in regions if region.category == "荒野")

    assert len(south) == 6
    assert len(frontier) == 1
    assert len(north) == 4
    assert frontier[0].name == "镇岳防线"

    expected = {(x, y) for y in range(100) for x in range(100)}
    region_domains = [_domain_cells(region.coordinate_bands) for region in regions]
    terrain_domains = [
        _domain_cells(zone.coordinate_bands) for zone in view.terrain_zones
    ]

    assert _disjoint_union(region_domains) == expected
    assert _disjoint_union(terrain_domains) == expected
    assert all(_four_way_connected(domain) for domain in region_domains)
    assert all(_four_way_connected(domain) for domain in terrain_domains)


def test_map_locations_and_location_queries_share_one_world_fact(
    world: WorldService,
) -> None:
    mapped = next(item for item in world.map_view().locations if item.name == "溪隐台")
    queried = world.locate(LocationQuery(location_name="溪隐台"))

    assert mapped.key == queried.location_key == "溪隐台"
    assert mapped.xy == queried.xy == (15, 17)
    assert mapped.region == queried.region == "青岚州"
    assert mapped.terrain == queried.terrain == "溪谷"
    assert mapped.altitude == queried.altitude
    assert mapped.available_functions == queried.available_functions


def test_map_roads_are_bounded_continuous_location_links(world: WorldService) -> None:
    view = world.map_view()
    locations = {location.key: location.xy for location in view.locations}
    location_by_xy = {location.xy: location.key for location in view.locations}

    for road in view.roads:
        assert road.coordinates[0] == locations[road.start_key]
        assert road.coordinates[-1] == locations[road.end_key]
        assert not {
            location_by_xy[xy] for xy in road.coordinates[1:-1] if xy in location_by_xy
        }
        for previous, current in pairwise(road.coordinates):
            assert (
                max(abs(current[0] - previous[0]), abs(current[1] - previous[1])) == 1
            )


def test_map_road_network_reaches_every_location(world: WorldService) -> None:
    view = world.map_view()
    graph: dict[str, set[str]] = defaultdict(set)
    for road in view.roads:
        graph[road.start_key].add(road.end_key)
        graph[road.end_key].add(road.start_key)

    reached: set[str] = set()
    queue = deque([view.birthplace_key])
    while queue:
        key = queue.popleft()
        if key in reached:
            continue
        reached.add(key)
        queue.extend(graph[key] - reached)

    assert reached == {location.key for location in view.locations}


@pytest.mark.parametrize(
    "field",
    ("地点类别", "行政层级", "形制", "显示名称"),
)
def test_location_body_does_not_repeat_directory_identity(field: str) -> None:
    with pytest.raises(JsonDataError, match="身份和层级必须由目录表达"):
        _validate_location_data(
            {
                "坐标": [8, 8],
                "说明": "溪隐台",
                "可用功能": ["闭关"],
                field: "重复身份",
            },
            "溪隐台",
            {"闭关": ((), ())},
        )


def test_location_feature_requirements_are_enforced() -> None:
    with pytest.raises(JsonDataError, match="字段没有对应功能要求"):
        _validate_location_data(
            {
                "坐标": [8, 8],
                "说明": "溪隐台",
                "可用功能": ["闭关"],
                "单次遭遇敌人数": [1, 2],
            },
            "溪隐台",
            {"闭关": ((), ())},
        )
    with pytest.raises(JsonDataError, match="单次遭遇敌人数"):
        _validate_location_data(
            {
                "坐标": [8, 8],
                "说明": "溪隐台",
                "可用功能": ["探险"],
            },
            "溪隐台",
            {"探险": ((), ("单次遭遇敌人数",))},
        )


def _negative_run(values: tuple[int, ...]) -> int:
    return next(
        (index for index, value in enumerate(values) if value >= 0), len(values)
    )


def _domain_cells(bands: object) -> set[tuple[int, int]]:
    return {
        (x, band.y)
        for band in bands
        for start, end in band.x_ranges
        for x in range(start, end + 1)
    }


def _disjoint_union(domains: list[set[tuple[int, int]]]) -> set[tuple[int, int]]:
    merged: set[tuple[int, int]] = set()
    for domain in domains:
        assert merged.isdisjoint(domain)
        merged.update(domain)
    return merged


def _four_way_connected(domain: set[tuple[int, int]]) -> bool:
    reached: set[tuple[int, int]] = set()
    queue = deque([next(iter(domain))])
    while queue:
        xy = queue.popleft()
        if xy in reached:
            continue
        reached.add(xy)
        x, y = xy
        queue.extend(
            neighbor
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if neighbor in domain and neighbor not in reached
        )
    return reached == domain
