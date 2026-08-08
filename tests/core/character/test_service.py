from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.character import CharacterService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, StateAddress
from game.core.player_state import PlayerStateService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CharacterExistsError,
    CreateCharacterFeature,
    CreateCharacterRequest,
    InvalidCreateCharacterError,
)


def _run(awaitable):
    return asyncio.run(awaitable)


def _feature(tmp_path: Path) -> tuple[CreateCharacterFeature, DatabaseService]:
    root = Path(__file__).resolve().parents[3]
    data = JsonDataService(root / "data")
    data.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    world = WorldService(data)
    world.initialize()
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    character = CharacterService(data, database, player_state)
    character.initialize()
    feature = CreateCharacterFeature(data, world, character)
    feature.initialize()
    return feature, database


def test_create_character_commits_all_initial_states(tmp_path: Path) -> None:
    feature, database = _feature(tmp_path)

    result = _run(
        feature.create(CreateCharacterRequest("qq-1", "event-1", "林远", "男"))
    )

    assert result.realm_id == "510001"
    assert result.location_name == "溪隐台"
    assert result.initial_items == (("小还丹", "01", 3), ("养神丹", "01", 2))
    snapshots = _run(database.list_for_user("qq-1"))
    assert {
        (item.address.state_type, item.address.state_key) for item in snapshots
    } == {
        ("character", "main"),
        ("cultivation", "main"),
        ("weapon", "main"),
        ("player_state", "main"),
        ("inventory", "丹药:100002:01"),
        ("inventory", "丹药:100005:01"),
    }
    character = _run(database.get(StateAddress("qq-1", "character", "main")))
    assert character is not None
    assert character.value["位置"] == {"xy": (15, 17)}
    assert "状态" not in character.value


def test_same_create_request_is_idempotent(tmp_path: Path) -> None:
    feature, database = _feature(tmp_path)
    request = CreateCharacterRequest("qq-1", "event-1", "林远", "男")

    first = _run(feature.create(request))
    second = _run(feature.create(request))

    assert first.replayed is False
    assert second.replayed is True
    assert database.status().transaction_count == 1


def test_existing_character_rejects_new_create_request(tmp_path: Path) -> None:
    feature, _ = _feature(tmp_path)
    _run(feature.create(CreateCharacterRequest("qq-1", "event-1", "林远", "男")))

    with pytest.raises(CharacterExistsError):
        _run(feature.create(CreateCharacterRequest("qq-1", "event-2", "白芷", "女")))


def test_invalid_input_has_no_database_side_effect(tmp_path: Path) -> None:
    feature, database = _feature(tmp_path)

    with pytest.raises(InvalidCreateCharacterError):
        _run(feature.create(CreateCharacterRequest("qq-1", "event-1", "A", "男")))

    assert _run(database.list_for_user("qq-1")) == ()
