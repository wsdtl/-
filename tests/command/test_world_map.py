from __future__ import annotations

import ast
import asyncio
import json
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from game.core.data import JsonDataService
from game.core.world import WorldService
from game.features.ditu import WorldMapFeature
from main import create_app
from message import RenderedMessage, render_local_message

world_map_entry = import_module("game.cmd.地图.entry")
world_map_site = import_module("game.cmd.地图.site")


def _world() -> WorldService:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    world = WorldService(data)
    world.initialize()
    return world


def _map_feature() -> WorldMapFeature:
    feature = WorldMapFeature(_world())
    feature.initialize()
    return feature


def test_world_map_routes_are_public_read_only_endpoints() -> None:
    app = create_app()
    methods_by_path = {
        route.path: getattr(route, "methods", set()) for route in app.routes
    }

    assert methods_by_path["/world-map"] == {"GET"}
    assert methods_by_path["/world-map/data"] == {"GET"}
    assert methods_by_path["/game-console"] == {"GET"}
    assert methods_by_path["/game-console/login"] == {"POST"}


def test_world_map_page_is_a_data_driven_plugin_shell() -> None:
    response = asyncio.run(world_map_site.world_map_page())
    html = response.body.decode("utf-8")

    assert 'id="atlasRoot"' in html
    assert 'id="worldMap"' not in html
    assert "晓楠修仙界" not in html
    assert "溪隐台" not in html


def test_world_map_plugin_does_not_bundle_world_facts() -> None:
    root = Path(__file__).resolve().parents[2]
    static_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "static" / "world-map").iterdir()
        if path.is_file()
    )
    view = _world().map_view()

    assert view.name not in static_source
    assert all(location.name not in static_source for location in view.locations)
    assert all(region.name not in static_source for region in view.regions)
    assert all(region.category not in static_source for region in view.regions)
    assert all(
        zone.name not in static_source and zone.terrain not in static_source
        for zone in view.terrain_zones
    )
    assert all(road.road_type not in static_source for road in view.roads)


def test_world_map_endpoint_serializes_core_snapshot(monkeypatch) -> None:
    feature = _map_feature()
    monkeypatch.setattr(
        world_map_site,
        "current_game_services",
        lambda: SimpleNamespace(features=SimpleNamespace(ditu=feature)),
    )

    response = asyncio.run(world_map_site.world_map_data())
    payload = json.loads(response.body)

    assert payload["schema"] == "game.world_map.presentation"
    assert payload["version"] == 2
    assert payload["name"] == "晓楠修仙界"
    assert len(payload["surface"]) == 100
    assert len(payload["locations"]) == 81
    assert len(payload["terrain_zones"]) == 85
    assert len(payload["roads"]) == 118
    assert all("coordinate_bands" in region for region in payload["regions"])
    assert all("coordinate_bands" in zone for zone in payload["terrain_zones"])


def test_world_map_command_uses_snapshot_facts_and_public_link() -> None:
    overview = _map_feature().overview()
    url = "https://example.test/world-map"
    message = world_map_entry._entry_message(overview, url)
    rendered = render_local_message(message, markdown=False)

    assert isinstance(rendered, RenderedMessage)
    assert overview.name in rendered.content
    assert overview.description in rendered.content
    assert "范围: 100 × 100" in rendered.content
    assert f"区域: {overview.region_count}处" in rendered.content
    assert f"地点: {overview.location_count}处" in rendered.content
    assert f"道路: {overview.road_count}条" in rendered.content
    assert f"打开{overview.name}地图" in rendered.content
    assert url in rendered.content
    assert tuple((action.action_id, action.data) for action in rendered.actions) == (
        ("world_map.open", url),
    )


def test_world_map_and_heavenly_dao_console_are_separate_components() -> None:
    root = Path(__file__).resolve().parents[2]
    command_root = root / "game" / "cmd"
    admin_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (command_root / "天道后台").glob("*.py")
    )
    map_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (command_root / "地图").glob("*.py")
    )

    assert not (command_root / "web").exists()
    assert "/world-map" not in admin_source
    assert "game-console" not in map_source


def test_command_router_aggregator_has_no_chinese_imports() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "game" / "cmd" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]

    assert all(module.isascii() for module in imported_modules)
    assert "import_module" in source
    assert "iter_modules" in source
