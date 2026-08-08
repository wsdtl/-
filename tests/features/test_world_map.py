from __future__ import annotations

from pathlib import Path

import pytest

from game.core.data import JsonDataService
from game.core.world import WorldService
from game.features.ditu import WorldMapFeature


def _world(*, initialize: bool = True) -> WorldService:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    world = WorldService(data)
    if initialize:
        world.initialize()
    return world


def test_world_map_feature_derives_overview_from_core_snapshot() -> None:
    world = _world()
    feature = WorldMapFeature(world)

    overview = feature.initialize()

    assert feature.snapshot() is world.map_view()
    assert overview.name == feature.snapshot().name
    assert (overview.width, overview.height) == (100, 100)
    assert overview.region_count == len(feature.snapshot().regions)
    assert overview.location_count == len(feature.snapshot().locations)
    assert overview.road_count == len(feature.snapshot().roads)


def test_world_map_feature_requires_initialized_world() -> None:
    feature = WorldMapFeature(_world(initialize=False))

    with pytest.raises(RuntimeError, match="世界地点微服务必须先于"):
        feature.initialize()
