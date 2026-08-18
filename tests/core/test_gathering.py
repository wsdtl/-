from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from game.core.asset import AssetService
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, StateMutation, TransactionCommand
from game.core.forging import ForgingService
from game.core.gathering import (
    GatheringConflictError,
    GatheringLeaderRequiredError,
    GatheringService,
    GatheringStartCommand,
)
from game.core.growth import GrowthService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.team import TeamService
from game.core.world import WorldService
from game.features.caikuang import OreGatheringFeature
from game.features.caiyao import HerbGatheringFeature
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
    gathering = GatheringService(
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
    gathering.initialize()
    caiyao = HerbGatheringFeature(data, gathering, asset, team)
    caiyao.initialize()
    caikuang = OreGatheringFeature(data, gathering, asset, team)
    caikuang.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    return (
        database,
        player_state,
        team,
        companion,
        asset,
        gathering,
        caiyao,
        caikuang,
        create,
    )


def _create(
    create: CreateCharacterFeature,
    user_id: str,
    name: str,
    gender: str = "男",
) -> None:
    _run(
        create.create(
            CreateCharacterRequest(user_id, f"create-{user_id}", name, gender)
        )
    )


def test_herb_gathering_unlocks_full_rounds_and_settles_inventory(
    tmp_path: Path,
) -> None:
    database, player_state, _, _, asset, gathering, _, _, create = _services(tmp_path)
    _create(create, "qq-1", "林远")
    started_at = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)

    started = _run(
        gathering.start(
            GatheringStartCommand(
                "采药",
                "qq-1",
                "herb-1",
                ("qq-1",),
                seed=7,
                started_at=started_at,
            )
        )
    )

    assert started.maximum_ends_at == started_at + timedelta(minutes=30)
    assert started.gathering_unit_count == 1
    before_round = _run(
        gathering.progress("采药", "qq-1", now=started_at + timedelta(seconds=299))
    )
    assert before_round.completed_rounds == 0
    assert before_round.group_quantity == 0
    one_round = _run(
        gathering.progress("采药", "qq-1", now=started_at + timedelta(seconds=300))
    )
    assert one_round.completed_rounds == 1
    assert one_round.group_quantity == 1
    assert sum(item.quantity for item in one_round.own_items) == 1

    with pytest.raises(GatheringConflictError, match="采药"):
        _run(
            gathering.start(
                GatheringStartCommand(
                    "采矿",
                    "qq-1",
                    "ore-conflict",
                    ("qq-1",),
                    started_at=started_at,
                )
            )
        )

    settlement = _run(
        gathering.settle(
            "采药",
            "qq-1",
            "finish-herb",
            now=started_at + timedelta(minutes=17, seconds=40),
        )
    )
    assert settlement.completed_rounds == 3
    assert settlement.total_quantity == 3
    assert sum(item.quantity for item in settlement.users[0].items) == 3
    for item in settlement.users[0].items:
        stacks = _run(asset.inventory_stacks("qq-1", item.item_id))
        assert (
            sum(
                stack.quantity
                for stack in stacks
                if stack.grade.grade_id == item.grade_id
            )
            == item.quantity
        )
    state = _run(player_state.current("qq-1"))
    assert state is not None and state.states["行为"].name == "空闲"
    assert _run(gathering.settle("采药", "qq-1", "finish-herb")).replayed is True
    assert database.status().transaction_count >= 3


def test_team_mining_is_led_once_and_settled_per_user(tmp_path: Path) -> None:
    _, player_state, team, _, _, gathering, _, caikuang, create = _services(tmp_path)
    _create(create, "qq-1", "林远")
    _create(create, "qq-2", "白川")
    _run(team.invite("qq-1", "qq-2", "invite-2"))
    _run(team.accept("qq-2", "accept-2"))
    started_at = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)

    started = _run(
        gathering.start(
            GatheringStartCommand(
                "采矿",
                "qq-1",
                "ore-team",
                ("qq-1", "qq-2"),
                seed=11,
                started_at=started_at,
            )
        )
    )
    assert started.participant_count == 2
    assert started.gathering_unit_count == 2
    owner_guard = _run(player_state.authorize("qq-1", "自主空闲"))
    member_guard = _run(player_state.authorize("qq-2", "自主空闲"))
    assert "正在带领同行修士采矿" in owner_guard.reason
    assert "正在跟随领队采矿" in member_guard.reason
    member_progress = _run(
        caikuang.progress("qq-2", now=started_at + timedelta(minutes=5))
    )
    assert member_progress.group_quantity == 2
    assert sum(item.quantity for item in member_progress.own_items) == 1
    assert member_progress.can_end is False
    with pytest.raises(GatheringLeaderRequiredError, match="领队统一"):
        _run(
            gathering.settle(
                "采矿",
                "qq-2",
                "member-finish",
                now=started_at + timedelta(minutes=5),
            )
        )

    result = _run(
        gathering.settle(
            "采矿",
            "qq-1",
            "leader-finish",
            now=started_at + timedelta(minutes=5),
        )
    )
    assert result.total_quantity == 2
    assert [sum(item.quantity for item in user.items) for user in result.users] == [
        1,
        1,
    ]
    for user_id in ("qq-1", "qq-2"):
        state = _run(player_state.current(user_id))
        assert state is not None and state.states["行为"].name == "空闲"


def test_living_active_companion_adds_one_gathering_unit(tmp_path: Path) -> None:
    database, _, _, companion, _, gathering, _, _, create = _services(tmp_path)
    _create(create, "qq-1", "林远", "男")
    definition = next(
        value for value in companion.local_cultivators("溪隐台") if value.gender == "女"
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "full-affection",
                "测试道侣关系",
                (
                    StateMutation(
                        "qq-1",
                        "companion_relation",
                        definition.companion_id,
                        {
                            "当前好感": 100,
                            "赠礼累计": {},
                            "首次圆满时间": "2026-08-18T09:00:00+00:00",
                        },
                        0,
                    ),
                ),
                {},
            )
        )
    )
    invitation = _run(
        companion.plan_invitation(
            "qq-1",
            definition.companion_id,
            player_gender="男",
            occurred_at="2026-08-18T09:05:00+00:00",
        )
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "invite-companion",
                "测试邀约道侣",
                invitation.operations,
                {},
            )
        )
    )
    started_at = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)

    started = _run(
        gathering.start(
            GatheringStartCommand(
                "采药",
                "qq-1",
                "herb-companion",
                ("qq-1",),
                seed=17,
                started_at=started_at,
            )
        )
    )
    progress = _run(
        gathering.progress("采药", "qq-1", now=started_at + timedelta(minutes=5))
    )

    assert started.gathering_unit_count == 2
    assert progress.group_quantity == 2
    assert sum(item.quantity for item in progress.own_items) == 2
