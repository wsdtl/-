from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.core.character import CharacterService
from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.player_state import PlayerStateService
from game.core.world import WorldService
from game.features.chakan_juese import (
    CharacterOverviewFeature,
    CharacterOverviewMissingError,
)
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from message import DocumentMessage
from message.renderers.plain_text import render_plain_text


def _run(awaitable):
    return asyncio.run(awaitable)


def _features(
    tmp_path: Path,
) -> tuple[CreateCharacterFeature, CharacterOverviewFeature]:
    root = Path(__file__).resolve().parents[2]
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
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    overview = CharacterOverviewFeature(character, player_state, world)
    overview.initialize()
    return create, overview


def test_character_overview_combines_owned_service_results(
    tmp_path: Path, monkeypatch
) -> None:
    create, overview = _features(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "event-1", "林远", "男")))

    result = _run(overview.inspect("qq-1"))
    character = result.character

    assert (character.name, character.gender) == ("林远", "男")
    assert (character.realm_name, character.level) == ("灵动", 1)
    assert character.xy == (15, 17)
    assert dict(character.attributes)["攻击"] == 5
    assert dict(character.resources) == {"血气": 100, "精神": 100, "护盾": 0}
    assert character.cultivation_slots == (("功法", 6), ("真意", 6), ("气机", 6))
    assert character.equipped_content == ()
    assert character.weapon.stage == "凡器"
    assert character.weapon.attack == 10
    assert character.weapon.open_law_slots == 0
    assert character.inventory.stack_count == 2
    assert character.inventory.total_quantity == 5
    assert result.location_name == "溪隐台"
    assert result.states == (("行为", "空闲"), ("队伍", "未组队"), ("控制", "自主"))

    class RecordingManager:
        message: DocumentMessage | None = None

        async def send(self, message: DocumentMessage) -> None:
            self.message = message

    class OverviewStub:
        async def inspect(self, user_id: str):
            assert user_id == "qq-1"
            return result

    command_module = import_module("game.cmd.角色")
    monkeypatch.setattr(
        command_module,
        "current_game_services",
        lambda: SimpleNamespace(features=SimpleNamespace(chakan_juese=OverviewStub())),
    )
    manager = RecordingManager()
    _run(command_module.show_character(user_id="qq-1", manager=manager))

    assert manager.message is not None
    content = render_plain_text(manager.message.document)
    assert "林远" in content
    assert "灵动" in content
    assert "溪隐台" in content
    assert "功法: 0/6" in content
    assert "无名器胚" in content
    assert "攻击: 10" in content


def test_character_overview_rejects_missing_character(tmp_path: Path) -> None:
    _, overview = _features(tmp_path)

    with pytest.raises(CharacterOverviewMissingError):
        _run(overview.inspect("qq-1"))
