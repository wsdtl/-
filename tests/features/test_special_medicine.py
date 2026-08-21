from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import (
    DatabaseService,
    StateMutation,
    TransactionCommand,
)
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.location import LocationMoveCommand, LocationService
from game.core.medicine import MedicineService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.world import LocationQuery, WorldService
from game.features.butian import ButianError, ButianFeature
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.guiyuan import GuiyuanConflictError, GuiyuanError, GuiyuanFeature
from game.features.yixing import YixingFeature
from tests.support import innate_treasure_service


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
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    medicine = MedicineService(data, asset)
    medicine.initialize()
    forging = ForgingService(data, database, asset, world, location, innate_treasure_service(data, database))
    forging.initialize()
    companion = CompanionService(data, database, growth, forging)
    companion.initialize()
    character = CharacterService(
        data, database, player_state, location, asset, growth, forging
    )
    character.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    guiyuan = GuiyuanFeature(
        data,
        medicine,
        companion,
        asset,
        player_state,
        location,
        world,
        database,
    )
    guiyuan.initialize()
    butian = ButianFeature(
        data,
        medicine,
        character,
        companion,
        asset,
        player_state,
        location,
        world,
        database,
    )
    butian.initialize()
    yixing = YixingFeature(
        data,
        medicine,
        character,
        asset,
        player_state,
        location,
        world,
        database,
    )
    yixing.initialize()
    return {
        "growth": growth,
        "database": database,
        "world": world,
        "location": location,
        "asset": asset,
        "companion": companion,
        "character": character,
        "create": create,
        "guiyuan": guiyuan,
        "butian": butian,
        "yixing": yixing,
    }


def _create(services, user_id: str = "qq-1", gender: str = "男") -> None:
    _run(
        services["create"].create(
            CreateCharacterRequest(user_id, f"create-{user_id}", "林远", gender)
        )
    )


def _grant(services, item_id: str, quantity: int, request_id: str) -> None:
    plan = _run(
        services["asset"].plan_inventory_changes(
            "qq-1", (InventoryAdjustment(item_id, "01", quantity),)
        )
    )
    _run(
        services["database"].commit(
            TransactionCommand(
                "qq-1", request_id, "测试入库", plan.operations, {"物品": item_id}
            )
        )
    )


def _move(services, location_name: str, request_id: str) -> None:
    origin = _run(services["location"].current("qq-1"))
    destination = services["world"].locate(LocationQuery(location_name=location_name))
    _run(
        services["location"].move(
            LocationMoveCommand("qq-1", request_id, origin.xy, destination.xy)
        )
    )


def _invite_companion(services) -> str:
    companion = services["companion"]
    definition = next(
        companion.definition(value.companion_id)
        for value in companion.local_cultivators("溪隐台")
        if value.gender == "女"
    )
    _run(
        services["database"].commit(
            TransactionCommand(
                "qq-1",
                "prepare-relation",
                "测试关系",
                (
                    StateMutation(
                        "qq-1",
                        "companion_relation",
                        definition.companion_id,
                        {"当前好感": 100, "赠礼累计": {}},
                        0,
                    ),
                ),
                {},
            )
        )
    )
    plan = _run(
        companion.plan_invitation(
            "qq-1",
            definition.companion_id,
            player_gender="男",
            occurred_at="2026-08-19T00:00:00+00:00",
        )
    )
    _run(
        services["database"].commit(
            TransactionCommand(
                "qq-1", "invite-companion", "测试邀约", plan.operations, {}
            )
        )
    )
    return definition.companion_id


def _grow_to_breakthrough(services, target: str) -> None:
    experience = sum(
        services["growth"].experience_required(level) for level in range(1, 6)
    )
    if target == "人物":
        plan = _run(services["character"].plan_growth("qq-1", experience=experience))
        operations = plan.operations
    else:
        plan = _run(services["companion"].plan_growth("qq-1", experience=experience))
        operations = plan.operations
    _run(
        services["database"].commit(
            TransactionCommand(
                "qq-1", f"grow-{target}", "测试成长", operations, {"目标": target}
            )
        )
    )
    if target == "人物":
        breakthrough = _run(
            services["character"].plan_breakthrough("qq-1", medicine_id="140001")
        )
        operations = (breakthrough.operation,)
    else:
        breakthrough = _run(
            services["companion"].plan_breakthrough("qq-1", medicine_id="140001")
        )
        operations = breakthrough.operations
    _run(
        services["database"].commit(
            TransactionCommand(
                "qq-1",
                f"breakthrough-{target}",
                "测试纯突破",
                operations,
                {"目标": target},
            )
        )
    )


def test_guiyuan_changes_only_selected_companion_build_and_is_atomic(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    _create(services)
    _invite_companion(services)
    _move(services, "归元观", "move-guiyuan")
    _grant(services, "160001", 1, "grant-guiyuan")
    before = _run(services["companion"].active_instance("qq-1")).instance

    result = _run(services["guiyuan"].reset("qq-1", "guiyuan-1", "功法"))
    after = _run(services["companion"].active_instance("qq-1")).instance
    replay = _run(services["guiyuan"].reset("qq-1", "guiyuan-1", "功法"))

    assert result.content_count == len(before.cultivation["功法"])
    assert len(after.cultivation["功法"]) == len(before.cultivation["功法"])
    assert after.cultivation["真意"] == before.cultivation["真意"]
    assert after.cultivation["气机"] == before.cultivation["气机"]
    assert after.weapon_laws == before.weapon_laws
    assert replay.replayed is True
    assert _run(services["asset"].inventory_stacks("qq-1", "160001")) == ()

    frozen = after
    with pytest.raises(GuiyuanError, match="没有万法归元丹"):
        _run(services["guiyuan"].reset("qq-1", "guiyuan-2", "真意"))
    assert _run(services["companion"].active_instance("qq-1")).instance == frozen
    with pytest.raises(GuiyuanConflictError):
        _run(services["guiyuan"].reset("qq-1", "guiyuan-1", "气机"))


@pytest.mark.parametrize("target", ["人物", "道侣"])
def test_butian_corrects_pure_breakthrough_once_for_each_target(
    tmp_path: Path, target: str
) -> None:
    services = _services(tmp_path)
    _create(services)
    companion_id = _invite_companion(services) if target == "道侣" else ""
    _grow_to_breakthrough(services, target)
    _move(services, "裂天原", "move-butian")
    _grant(services, "160002", 1, "grant-butian")

    if target == "人物":
        before = dict(_run(services["character"].profile("qq-1")).attributes)
    else:
        before = dict(
            _run(services["companion"].instance("qq-1", companion_id)).attributes
        )
    result = _run(
        services["butian"].apply(
            "qq-1", "butian-1", target, "炼气", "140002"
        )
    )
    replay = _run(
        services["butian"].apply(
            "qq-1", "butian-1", target, "炼气", "140002"
        )
    )
    if target == "人物":
        after = dict(_run(services["character"].profile("qq-1")).attributes)
    else:
        after = dict(
            _run(services["companion"].instance("qq-1", companion_id)).attributes
        )

    assert result.attribute == "血气上限"
    assert after["血气上限"] == pytest.approx(before["血气上限"] + result.value)
    assert replay.replayed is True
    assert _run(services["asset"].inventory_stacks("qq-1", "160002")) == ()
    with pytest.raises(ButianError, match="已经补正"):
        _run(
            services["butian"].apply(
                "qq-1", "butian-2", target, "炼气", "140003"
            )
        )


def test_butian_rejects_multi_attribute_source_without_consuming(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    _create(services)
    _grow_to_breakthrough(services, "人物")
    _move(services, "裂天原", "move-butian")
    _grant(services, "160002", 1, "grant-butian")

    with pytest.raises(ButianError, match="只提供一项永久属性"):
        _run(
            services["butian"].apply(
                "qq-1", "butian-invalid", "人物", "炼气", "140007"
            )
        )

    stacks = _run(services["asset"].inventory_stacks("qq-1", "160002"))
    assert stacks[0].quantity == 1


def test_yixing_changes_only_player_gender_and_preserves_companion_relation(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    _create(services)
    companion_id = _invite_companion(services)
    relation_before = _run(services["companion"].relation("qq-1", companion_id))
    active_before = _run(services["companion"].active("qq-1"))
    _move(services, "太素坊", "move-yixing")
    _grant(services, "160004", 1, "grant-yixing")

    result = _run(services["yixing"].change("qq-1", "yixing-1"))
    replay = _run(services["yixing"].change("qq-1", "yixing-1"))

    assert (result.gender_before, result.gender_after) == ("男", "女")
    assert _run(services["character"].profile("qq-1")).gender == "女"
    assert _run(services["companion"].relation("qq-1", companion_id)) == relation_before
    assert _run(services["companion"].active("qq-1")) == active_before
    assert replay.replayed is True
    assert _run(services["asset"].inventory_stacks("qq-1", "160004")) == ()
