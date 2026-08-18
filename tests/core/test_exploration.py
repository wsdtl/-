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
from game.core.database import DatabaseService, StateAddress
from game.core.enemy import EnemyService
from game.core.exploration import (
    ExplorationLeaderRequiredError,
    ExplorationNotFinishedError,
    ExplorationService,
    ExplorationStartCommand,
)
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.item_catalog import ItemCatalogService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.team import TeamService
from game.core.world import LocationQuery, WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.tanxian import ExplorationFeature


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
    team = TeamService(data, database, player_state)
    team.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    forging = ForgingService(data, database, asset, world, location)
    forging.initialize()
    companion = CompanionService(data, database, growth, forging)
    companion.initialize()
    item_catalog = ItemCatalogService(data)
    item_catalog.initialize()
    character = CharacterService(
        data, database, player_state, location, asset, growth, forging
    )
    character.initialize()
    enemy = EnemyService(data, pool, growth, asset, forging)
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
    exploration_feature = ExplorationFeature(
        data, exploration, item_catalog, asset, team
    )
    exploration_feature.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    return (
        database,
        player_state,
        character,
        asset,
        create,
        world,
        exploration,
        team,
        exploration_feature,
    )


def test_exploration_precomputes_unlocks_and_settles_once(tmp_path: Path) -> None:
    database, player_state, character, asset, create, _, exploration, _, _ = _services(
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
    assert started.ends_at == started_at + timedelta(seconds=started.battle_count * 120)
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
        stack.quantity - remaining.get(stack.stack_key, 0) for stack in medicines_before
    )
    session = _run(database.list_for_user("qq-1", state_type="exploration_session"))[0]
    recorded = sum(row["数量"] for row in session.value["用户结果"]["qq-1"]["消耗"])
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
    settlement = _run(exploration.settle("qq-1", "settle-1", now=started.ends_at))
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


def test_team_leader_starts_one_real_exploration_for_all_players(
    tmp_path: Path,
) -> None:
    database, player_state, _, _, create, _, exploration, team, feature = _services(
        tmp_path
    )
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    _run(create.create(CreateCharacterRequest("qq-2", "create-2", "白川", "男")))
    _run(team.invite("qq-1", "qq-2", "invite-2"))
    _run(team.accept("qq-2", "accept-2"))

    started = _run(feature.start("qq-1", "explore-team"))

    assert started.participant_count == 2
    session = _run(
        database.get(StateAddress("qq-1", "exploration_session", started.session_id))
    )
    assert session is not None
    assert session.value["参与用户"] == ("qq-1", "qq-2")
    for user_id in ("qq-1", "qq-2"):
        state = _run(player_state.current(user_id))
        assert state is not None and state.states["行为"].name == "探险中"
        latest = _run(database.get(StateAddress(user_id, "exploration_latest", "main")))
        assert latest is not None
        assert latest.value["探险编号"] == started.session_id

    member_progress = _run(feature.progress("qq-2", now=started.ends_at))
    assert member_progress.can_settle is False
    with pytest.raises(ExplorationLeaderRequiredError, match="领队统一"):
        _run(
            exploration.settle(
                "qq-2",
                "member-settle",
                now=started.ends_at,
            )
        )
    _run(exploration.settle("qq-1", "leader-settle", now=started.ends_at))
    assert (
        _run(exploration.settle("qq-2", "member-view", now=started.ends_at)).replayed
        is True
    )


def test_world_exposes_enemy_multiplier_and_environment_id(tmp_path: Path) -> None:
    _, _, _, _, _, world, _, _, _ = _services(tmp_path)
    location = world.locate(LocationQuery(location_name="溪隐台"))

    assert location.enemy_multiplier == (1, 2)
    assert location.environment_id.startswith("61")
