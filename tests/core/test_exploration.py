from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from game.core.asset import AssetService
from game.core.character import CharacterService
from game.core.combat import CombatService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.enemy import EnemyService
from game.core.exploration import (
    ExplorationNotFinishedError,
    ExplorationService,
    ExplorationStartCommand,
)
from game.core.growth import GrowthService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.world import LocationQuery, WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)


def _run(awaitable):
    return asyncio.run(awaitable)


def _services(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    combat = CombatService(data)
    combat.initialize()
    pool = PoolService(data)
    pool.initialize()
    growth = GrowthService(data, pool)
    growth.initialize()
    world = WorldService(data)
    world.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    companion = CompanionService(data, database, growth)
    companion.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    character = CharacterService(
        data, database, player_state, location, asset, growth
    )
    character.initialize()
    enemy = EnemyService(data, pool, growth, asset)
    enemy.initialize()
    exploration = ExplorationService(
        data,
        database,
        world,
        location,
        character,
        companion,
        asset,
        player_state,
        enemy,
        combat,
    )
    exploration.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    return database, player_state, character, asset, create, world, exploration


def test_exploration_precomputes_unlocks_and_settles_once(tmp_path: Path) -> None:
    database, player_state, character, asset, create, _, exploration = _services(
        tmp_path
    )
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    medicines_before = _run(asset.recovery_medicines("qq-1"))
    assert medicines_before
    started_at = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)

    started = _run(
        exploration.start(
            ExplorationStartCommand(
                "qq-1",
                "explore-1",
                ("qq-1",),
                seed=7,
                started_at=started_at,
            )
        )
    )

    assert 1 <= started.battle_count <= 15
    assert started.ends_at == started_at + timedelta(
        seconds=started.battle_count * 120
    )
    state = _run(player_state.current("qq-1"))
    assert state is not None
    assert state.states["行为"].name == "探险中"
    assert state.states["行为"].context["探险编号"] == started.session_id
    battles = _run(database.list_for_user("qq-1", state_type="exploration_battle"))
    assert len(battles) == started.battle_count
    for battle in battles:
        assert battle.value["敌人数"] == (
            started.formal_unit_count * battle.value["敌人倍率"]
        )
        assert battle.value["我方存活"] <= started.formal_unit_count
    medicines_after = _run(asset.recovery_medicines("qq-1"))
    remaining = {stack.stack_key: stack.quantity for stack in medicines_after}
    deducted = sum(
        stack.quantity - remaining.get(stack.stack_key, 0)
        for stack in medicines_before
    )
    session = _run(database.list_for_user("qq-1", state_type="exploration_session"))[0]
    recorded = sum(
        row["数量"] for row in session.value["用户结果"]["qq-1"]["消耗"]
    )
    assert deducted == recorded

    initial = _run(exploration.progress("qq-1", now=started_at))
    assert initial.unlocked_battles == 0
    with pytest.raises(ExplorationNotFinishedError):
        _run(
            exploration.settle(
                "qq-1",
                "settle-early",
                now=started.ends_at - timedelta(seconds=1),
            )
        )

    complete = _run(exploration.progress("qq-1", now=started.ends_at))
    assert complete.unlocked_battles == started.battle_count
    assert complete.ended is True
    settlement = _run(
        exploration.settle("qq-1", "settle-1", now=started.ends_at)
    )
    assert len(settlement.users) == 1
    assert settlement.users[0].character_name == "林远"
    assert len(settlement.users[0].characters) == 1
    assert _run(player_state.current("qq-1")).states["行为"].name == "空闲"
    assert _run(character.profile("qq-1")).weapon.experience >= 0

    replay = _run(exploration.settle("qq-1", "settle-1", now=started.ends_at))
    assert replay.replayed is True
    assert database.status().transaction_count == 3


def test_indivisible_loot_is_floored_per_surviving_user() -> None:
    from game.core.enemy import EnemyDrop, EnemyReward
    from game.core.exploration.service import _allocate_rewards

    class Enemy:
        reward = EnemyReward(5, 0, (EnemyDrop("210001", "01", 1),))

    allocated = _allocate_rewards((Enemy(),), {"qq-1", "qq-2"})

    assert allocated["qq-1"]["灵石"] == 2
    assert allocated["qq-2"]["灵石"] == 2
    assert allocated["qq-1"]["掉落"] == {}
    assert allocated["qq-2"]["掉落"] == {}


def test_world_exposes_enemy_multiplier_and_environment_id(tmp_path: Path) -> None:
    _, _, _, _, _, world, _ = _services(tmp_path)
    location = world.locate(LocationQuery(location_name="溪隐台"))

    assert location.enemy_multiplier == (1, 2)
    assert location.environment_id.startswith("61")
