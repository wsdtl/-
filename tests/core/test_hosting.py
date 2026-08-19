from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.action_group import ActionGroupService
from game.core.asset import AssetService
from game.core.character import CharacterService
from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.hosting import HostingError, HostingService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService, StateTransitionCommand
from game.core.pool import PoolService
from game.core.sect import SectService
from game.core.team import TeamService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.duiwu import TeamFeature, TeamFeatureError
from game.features.tuoguan import HostingFeature


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
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    world = WorldService(data)
    world.initialize()
    state = PlayerStateService(data, database)
    state.initialize()
    team = TeamService(data, database, state)
    team.initialize()
    sect = SectService(data, database, state)
    sect.initialize()
    action_group = ActionGroupService(team, sect)
    action_group.initialize()
    hosting = HostingService(data, database, state, action_group)
    hosting.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    forging = ForgingService(data, database, asset, world, location)
    forging.initialize()
    character = CharacterService(
        data, database, state, location, asset, growth, forging
    )
    character.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    team_feature = TeamFeature(data, team, character, location, state)
    team_feature.initialize()
    hosting_feature = HostingFeature(data, hosting)
    hosting_feature.initialize()
    return state, create, team_feature, hosting, hosting_feature


def _create(create: CreateCharacterFeature, user_id: str, name: str) -> None:
    _run(create.create(CreateCharacterRequest(user_id, f"create-{user_id}", name, "男")))


def _join(team: TeamFeature) -> None:
    _run(team.invite("qq-1", "白川", "invite-qq-2"))
    _run(team.accept("qq-2", "accept-qq-2"))


def test_personal_hosting_is_persisted_replayed_and_cancelled(tmp_path: Path) -> None:
    state, create, _, hosting, feature = _services(tmp_path)
    _create(create, "qq-1", "林远")

    started = _run(feature.start("qq-1", "host-start"))
    assert (started.mode, started.participant_count) == ("personal", 1)
    snapshot = _run(state.current("qq-1"))
    assert snapshot is not None
    assert snapshot.states["控制"].state_id == "520010"
    assert dict(snapshot.states["控制"].context) == {
        "托管编号": "host-qq-1-host-start",
        "托管身份": "单人",
        "托管领队": None,
        "同行类型": "独行",
        "同行编号": None,
    }
    replayed = _run(hosting.start("qq-1", "host-start"))
    assert replayed.session_id == "host-qq-1-host-start"

    cancelled = _run(feature.cancel("qq-1", "host-cancel"))
    assert cancelled.participant_count == 1
    snapshot = _run(state.current("qq-1"))
    assert snapshot is not None
    assert snapshot.states["控制"].state_id == "520009"
    assert dict(snapshot.states["控制"].context) == {}


def test_team_leader_hosts_and_cancels_every_member_atomically(tmp_path: Path) -> None:
    state, create, team, hosting, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _join(team)

    session = _run(hosting.start("qq-1", "team-host"))
    assert session.mode == "team"
    snapshots = _run(state.current_many(("qq-1", "qq-2")))
    assert [snapshot.states["控制"].context["托管身份"] for snapshot in snapshots] == [
        "领队",
        "跟随",
    ]
    assert {
        snapshot.states["控制"].context["托管编号"] for snapshot in snapshots
    } == {session.session_id}
    with pytest.raises(HostingError, match="member_cannot_cancel"):
        _run(hosting.cancel("qq-2", "member-cancel"))
    with pytest.raises(TeamFeatureError, match="actor_busy"):
        _run(team.leave("qq-2", "leave-hosting"))

    _run(hosting.cancel("qq-1", "team-cancel"))
    snapshots = _run(state.current_many(("qq-1", "qq-2")))
    assert {snapshot.states["控制"].state_id for snapshot in snapshots} == {"520009"}


def test_leader_cannot_host_when_a_participant_is_busy(tmp_path: Path) -> None:
    state, create, team, hosting, _ = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _join(team)
    _run(
        state.transition(
            StateTransitionCommand("qq-2", "busy", "行为", "520005")
        )
    )

    with pytest.raises(HostingError, match="participant_busy"):
        _run(hosting.start("qq-1", "busy-host"))
    snapshots = _run(state.current_many(("qq-1", "qq-2")))
    assert {snapshot.states["控制"].state_id for snapshot in snapshots} == {"520009"}
