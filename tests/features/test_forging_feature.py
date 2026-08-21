from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path

from game.core.asset import AssetService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, TransactionCommand
from game.core.forging import ForgingService
from game.core.location import LocationService
from game.core.world import LocationQuery, WorldService
from game.features.lianqi import ForgingFeature
from message import RenderedMessage, render_local_message
from tests.support import innate_treasure_service

forging_reply = import_module("game.cmd.专属.炼器.reply")


def _run(awaitable):
    return asyncio.run(awaitable)


def _feature(tmp_path: Path):
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
    feature = ForgingFeature(data, forging)
    feature.initialize()
    xy = world.locate(LocationQuery(location_name="天衡城")).xy
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "seed",
                "测试准备",
                (location.initial_mutation("qq-1", xy),),
                {},
            )
        )
    )
    return feature


def _render(message) -> RenderedMessage:
    rendered = render_local_message(message, markdown=False)
    assert isinstance(rendered, RenderedMessage)
    return rendered


def test_forging_overview_is_artisan_led_and_uses_json_actions(tmp_path: Path) -> None:
    feature = _feature(tmp_path)

    value = _run(feature.overview("qq-1"))
    message = forging_reply.overview(feature.copy(), value, feature.overview_actions())
    rendered = _render(message)

    assert value.location_name == "天衡城"
    assert value.artisan.name in rendered.content
    assert value.artisan.furnace_name in rendered.content
    assert "停下手中的活计" in rendered.content
    assert "灵器 · 16道器律" in rendered.content
    assert tuple(action.data for action in rendered.actions) == (
        "炼器 灵器",
        "炼器 法器",
        "炼器 法宝",
        "炼器 后天灵宝",
    )


def test_forging_preview_hides_commit_action_when_materials_are_missing(
    tmp_path: Path,
) -> None:
    feature = _feature(tmp_path)

    value = _run(feature.preview("qq-1", "太白惊鸿"))
    message = forging_reply.preview(
        feature.copy(), value, feature.preview_actions(value)
    )
    rendered = _render(message)

    assert not value.can_forge
    assert "顾" in rendered.content
    assert "这些材料还不足以成器" in rendered.content
    assert "开炉" not in tuple(action.label for action in rendered.actions)
