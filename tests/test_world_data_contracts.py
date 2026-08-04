"""世界地表使用 xy 定位，海拔只能来自统一地势。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from game.core.data import JsonDataService
from game.core.world import SurfaceCoordinate, WorldService


def test_locations_use_xy_and_derive_altitude_from_terrain() -> None:
    data = _data()
    world = data.entity("世界", "晓楠修仙界")
    terrain_values = data.dataset("地势")
    assert len(terrain_values) == 1
    terrain = next(iter(terrain_values.values()))
    heights = terrain["地表高度"]

    assert not {"地势", "坐标边界", "海拔范围", "水平每格米数"} & set(world)
    assert tuple(terrain["坐标边界"]["x轴"]) == (0, 99)
    assert tuple(terrain["坐标边界"]["y轴"]) == (0, 99)
    assert len(heights) == 100
    assert all(len(row) == 100 for row in heights)
    for location in data.entities("地点").values():
        assert "地形" not in location
        coordinate = tuple(location["坐标"])
        assert len(coordinate) == 2
        x, y = coordinate
        assert terrain["海拔范围"][0] <= heights[y][x] <= terrain["海拔范围"][1]


def test_regions_only_store_surface_bounds_and_terrain_partitions() -> None:
    data = _data()

    for region in data.entities("区域").values():
        assert set(region["坐标范围"]) == {"x轴", "y轴"}
        assert "海拔范围" not in region
        assert "默认地形" not in region
        assert region["地形分区"]


def test_location_region_membership_comes_from_data_metadata() -> None:
    data = _data()
    regions = set(data.entities("区域"))

    for identity in data.entities("地点"):
        record = data.entity_record("地点", identity)
        assert record.directory_owner in regions


def test_location_terrain_comes_from_region_terrain_partition() -> None:
    data = _data()
    world = WorldService(data)
    world.initialize()

    assert world.region_at(50, 19).identity == "丹霞州"
    assert world.terrain_at(50, 19) == "丘陵"
    assert world.terrain_zone_at(50, 19) == "丹霞城"
    assert world.terrain_at(51, 19) == "丘陵"

    for location in data.entities("地点").values():
        x, y = location["坐标"]
        expected = str(location["灵植池"][0]).removeprefix("灵植-")
        assert world.terrain_at(x, y) == expected


def test_every_surface_xy_resolves_one_region_and_valid_terrain() -> None:
    data = _data()
    world = WorldService(data)
    world.initialize()
    bounds = world.world().bounds
    environment_names = {
        str(environment["名称"])
        for environment in data.entities("战场环境").values()
    }

    for y in range(bounds.y_min, bounds.y_max + 1):
        for x in range(bounds.x_min, bounds.x_max + 1):
            assert world.region_at(x, y).bounds.contains(SurfaceCoordinate(x, y))
            assert world.terrain_at(x, y) in environment_names


@lru_cache(maxsize=1)
def _data() -> JsonDataService:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    return data
