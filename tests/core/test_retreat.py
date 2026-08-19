from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from game.core.action_group import ActionGroupService
from game.core.asset import AssetService, CultivationAcquisition
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, TransactionCommand
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.retreat import (
    RetreatLeaderRequiredError,
    RetreatService,
    RetreatStartCommand,
)
from game.core.sect import SectService
from game.core.team import TeamService
from game.core.world import WorldService
from game.features.biguan import RetreatFeature
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
    sect = SectService(data, database, player_state)
    sect.initialize()
    action_group = ActionGroupService(team, sect)
    action_group.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    forging = ForgingService(data, database, asset, world, location)
    forging.initialize()
    companion = CompanionService(data, database, growth, forging)
    companion.initialize()
    character = CharacterService(
        data, database, player_state, location, asset, growth, forging
    )
    character.initialize()
    retreat = RetreatService(
        data,
        database,
        world,
        location,
        character,
        companion,
        asset,
        player_state,
        pool,
    )
    retreat.initialize()
    feature = RetreatFeature(data, retreat, asset, action_group)
    feature.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    return (
        data,
        database,
        player_state,
        team,
        asset,
        character,
        retreat,
        feature,
        create,
    )


def test_retreat_unlocks_full_rounds_and_settles_early(tmp_path: Path) -> None:
    data, database, player_state, _, asset, character, retreat, _, create = _services(
        tmp_path
    )
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    damage = _run(character.plan_battle_settlement("qq-1", health=0, spirit=0))
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "damage-1",
                "测试伤势",
                damage.operations,
                {},
            )
        )
    )
    started_at = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    started = _run(
        retreat.start(
            RetreatStartCommand(
                "qq-1",
                "retreat-1",
                ("qq-1",),
                seed=7,
                started_at=started_at,
            )
        )
    )

    assert started.maximum_ends_at == started_at + timedelta(minutes=30)
    before_round = _run(
        retreat.progress("qq-1", now=started_at + timedelta(seconds=299))
    )
    assert before_round.completed_rounds == 0
    one_round = _run(retreat.progress("qq-1", now=started_at + timedelta(seconds=300)))
    assert one_round.completed_rounds == 1
    assert one_round.can_end is True

    settlement = _run(
        retreat.settle(
            "qq-1",
            "end-1",
            now=started_at + timedelta(minutes=17, seconds=40),
        )
    )
    assert settlement.completed_rounds == 3
    assert settlement.users[0].characters[0].experience_gained == 516
    assert settlement.users[0].characters[0].health > 0
    assert settlement.users[0].characters[0].spirit > 0
    state = _run(player_state.current("qq-1"))
    assert state is not None and state.states["行为"].name == "空闲"
    settled_progress = _run(
        retreat.progress("qq-1", now=started_at + timedelta(hours=1))
    )
    assert settled_progress.completed_rounds == 3
    assert settled_progress.settled is True
    assert _run(retreat.settle("qq-1", "end-1")).replayed is True

    technique_id = next(iter(data.entities("功法")))
    duplicate = _run(
        asset.plan_cultivation_acquisitions(
            "qq-1",
            (
                CultivationAcquisition("功法", technique_id, "01"),
                CultivationAcquisition("功法", technique_id, "01"),
                CultivationAcquisition("功法", technique_id, "02"),
                CultivationAcquisition("功法", technique_id, "01"),
            ),
        )
    )
    assert [result.outcome for result in duplicate.results] == [
        "新得",
        "复悟",
        "升品",
        "复悟",
    ]
    assert [operation.state_key for operation in duplicate.operations] == [technique_id]
    assert duplicate.operations[0].value == {"编号": technique_id, "品级": "02"}


def test_team_retreat_members_only_view_and_leader_ends(tmp_path: Path) -> None:
    _, _, player_state, team, _, _, retreat, feature, create = _services(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    _run(create.create(CreateCharacterRequest("qq-2", "create-2", "白川", "男")))
    _run(team.invite("qq-1", "qq-2", "invite-2"))
    _run(team.accept("qq-2", "accept-2"))
    started_at = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)

    started = _run(
        retreat.start(
            RetreatStartCommand(
                "qq-1",
                "retreat-team",
                ("qq-1", "qq-2"),
                seed=11,
                started_at=started_at,
            )
        )
    )
    assert started.participant_count == 2
    owner_guard = _run(player_state.authorize("qq-1", "自主空闲"))
    member_guard = _run(player_state.authorize("qq-2", "自主空闲"))
    assert "正在带领同行修士闭关" in owner_guard.reason
    assert "正在跟随领队闭关" in member_guard.reason
    member_progress = _run(
        feature.progress("qq-2", now=started_at + timedelta(minutes=5))
    )
    assert member_progress.completed_rounds == 1
    assert member_progress.can_end is False
    with pytest.raises(RetreatLeaderRequiredError, match="领队统一"):
        _run(
            retreat.settle(
                "qq-2",
                "member-end",
                now=started_at + timedelta(minutes=5),
            )
        )

    result = _run(
        retreat.settle(
            "qq-1",
            "leader-end",
            now=started_at + timedelta(minutes=5),
        )
    )
    assert result.completed_rounds == 1
    assert len(result.users) == 2
    assert _run(retreat.settle("qq-2", "member-view")).replayed is True
    for user_id in ("qq-1", "qq-2"):
        state = _run(player_state.current(user_id))
        assert state is not None and state.states["行为"].name == "空闲"
