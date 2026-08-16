from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from game.core.asset import AssetService
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.location import LocationMoveCommand, LocationService
from game.core.player_state import PlayerStateService, StateTransitionCommand
from game.core.world import LocationQuery, WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.weizhi import PositionFeature


def _run(awaitable):
    return asyncio.run(awaitable)


def _services(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    world = WorldService(data)
    world.initialize()
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    companion = CompanionService(data, database)
    companion.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    character = CharacterService(data, database, player_state, location, asset)
    character.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    position = PositionFeature(
        data,
        world,
        location,
        character,
        player_state,
        companion,
    )
    position.initialize()
    return database, player_state, location, create, position


def _create(create: CreateCharacterFeature, user_id: str, name: str) -> None:
    _run(
        create.create(CreateCharacterRequest(user_id, f"create-{user_id}", name, "男"))
    )


def test_position_is_created_atomically_and_not_repeated_in_character(
    tmp_path: Path,
) -> None:
    database, _, location, create, position = _services(tmp_path)
    _create(create, "qq-1", "林远")

    character = _run(database.list_for_user("qq-1", state_type="character"))[0]
    current = _run(location.current("qq-1"))
    view = _run(position.current("qq-1"))

    assert "位置" not in character.value
    assert current.xy == view.location.xy == (15, 17)
    assert view.location.location_name == "溪隐台"
    assert view.location.available_functions == ("修士",)
    assert view.local_cultivators
    assert all(value.realm_name == "灵动" for value in view.local_cultivators)


def test_nearby_cultivators_respect_distance_and_hidden_behavior(
    tmp_path: Path,
) -> None:
    _, player_state, location, create, position = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _create(create, "qq-3", "顾山")
    _run(location.move(LocationMoveCommand("qq-2", "move-2", (15, 17), (16, 18))))
    _run(location.move(LocationMoveCommand("qq-3", "move-3", (15, 17), (17, 17))))

    visible = _run(position.nearby_cultivators("qq-1"))
    assert [value.name for value in visible.cultivators] == ["白川"]
    assert visible.cultivators[0].direction == "东北方"
    assert visible.cultivators[0].distance == "约30里"

    _run(
        player_state.transition(
            StateTransitionCommand("qq-2", "retreat-2", "行为", "520004")
        )
    )
    hidden = _run(position.nearby_cultivators("qq-1"))
    assert hidden.cultivators == ()


def test_nearby_cultivators_use_surface_altitude_for_distance(
    tmp_path: Path,
) -> None:
    _, _, location, create, position = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _run(location.move(LocationMoveCommand("qq-1", "move-1", (15, 17), (94, 3))))
    _run(location.move(LocationMoveCommand("qq-2", "move-2", (15, 17), (95, 3))))

    result = _run(position.nearby_cultivators("qq-1"))

    # 两格水平相距一万米，但海拔相差两万余米，不属于十五公里三维范围。
    assert result.cultivators == ()


def test_all_companions_resolve_to_exact_world_locations(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    world = WorldService(data)
    world.initialize()
    database = DatabaseService(tmp_path / "companions.db")
    database.initialize()
    companion = CompanionService(data, database)
    status = companion.initialize()

    resolved = []
    for location in world.map_view().locations:
        view = world.locate(LocationQuery(location_name=location.name))
        local = companion.local_cultivators(location.name)
        assert bool(local) is bool(view.companion_pool)
        resolved.extend(local)

    assert len(resolved) == status.companion_count == 264
    assert len({value.companion_id for value in resolved}) == len(resolved)


def test_nearby_query_uses_coordinate_index(tmp_path: Path) -> None:
    database, _, _, create, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")

    with sqlite3.connect(database.path) as connection:
        plan = tuple(
            str(row[3])
            for row in connection.execute(
                """
                EXPLAIN QUERY PLAN
                SELECT user_id FROM player_location
                WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ?
                ORDER BY x, y, user_id
                """,
                (14, 16, 16, 18),
            )
        )

    assert any("ix_player_location_xy" in row for row in plan)


def test_nearby_locations_are_bounded_static_world_facts(tmp_path: Path) -> None:
    _, _, _, create, position = _services(tmp_path)
    _create(create, "qq-1", "林远")

    result = _run(position.nearby_locations("qq-1"))

    assert len(result.values) <= 8
    assert all(value.name != "溪隐台" for value in result.values)
    assert all(
        value.direction and value.distance.startswith("约") for value in result.values
    )


def test_position_copy_overview_and_buttons_are_json_driven(tmp_path: Path) -> None:
    _, _, location, create, position = _services(tmp_path)
    _create(create, "qq-1", "林远")

    copy = position.copy()
    overview = _run(position.nearby_overview("qq-1"))

    assert copy.overview_title.format(地点="溪隐台") == "溪隐台周边"
    assert len(overview.current.local_cultivators) == 3
    assert overview.visiting_cultivator_count == 0
    assert tuple(action.command for action in position.position_actions()) == (
        "附近",
        "地图",
    )
    assert tuple(action.command for action in position.nearby_overview_actions()) == (
        "附近 修士",
        "附近 地点",
        "位置",
    )

    paging = position.nearby_cultivator_actions(page=2, has_next=True)
    assert tuple(action.command for action in paging) == (
        "附近 修士 1",
        "附近 修士 3",
        "附近",
        "附近 地点",
        "位置",
    )

    _run(location.move(LocationMoveCommand("qq-1", "move-1", (15, 17), (25, 33))))
    nearby = _run(position.nearby_locations("qq-1"))
    actions = position.nearby_location_actions(nearby.values)
    assert tuple(action.command for action in actions) == (
        "去 雨花苑",
        "附近",
        "附近 修士",
        "位置",
    )
    assert len({action.action_id for action in actions}) == len(actions)
    assert tuple(
        action.command for action in position.nearby_overview_actions(nearby.values)
    ) == (
        "去 雨花苑",
        "附近 修士",
        "附近 地点",
        "位置",
    )
