"""世界地表使用 xy 定位，海拔只能来自统一地势。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from game.core.data import JsonDataService


def test_locations_use_xy_and_derive_altitude_from_terrain() -> None:
    data = _data()
    world = data.entity("世界", "晓楠修仙界")
    terrain = data.dataset("地势")[str(world["地势"])]
    heights = terrain["地表高度"]

    assert set(world["坐标边界"]) == {"x轴", "y轴"}
    assert tuple(world["海拔范围"]) == tuple(terrain["海拔范围"])
    for location in data.entities("地点").values():
        coordinate = tuple(location["坐标"])
        assert len(coordinate) == 2
        x, y = coordinate
        assert world["海拔范围"][0] <= heights[y][x] <= world["海拔范围"][1]


def test_regions_separate_surface_bounds_from_altitude_range() -> None:
    data = _data()

    for region in data.entities("区域").values():
        assert set(region["坐标范围"]) == {"x轴", "y轴"}
        assert len(region["海拔范围"]) == 2


@lru_cache(maxsize=1)
def _data() -> JsonDataService:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    return data
