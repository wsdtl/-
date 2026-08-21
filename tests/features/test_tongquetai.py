from __future__ import annotations

import asyncio
from pathlib import Path

from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.cultivation_transfer import CultivationTransferService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, TransactionCommand
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.item_catalog import ItemCatalogService
from game.core.location import LocationMoveCommand, LocationService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.world import LocationQuery, WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.daolv_jiejiao import (
    CompanionGiftRequest,
    CompanionInteractionFeature,
    CompanionInvitationRequest,
)
from game.features.tongquetai import TongquetaiFeature, TongquetaiRequest
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
    transfer = CultivationTransferService(data, growth)
    transfer.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    world = WorldService(data)
    world.initialize()
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    catalog = ItemCatalogService(data)
    catalog.initialize()
    asset = AssetService(data, database)
    asset.initialize()
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
    interaction = CompanionInteractionFeature(
        data,
        companion,
        catalog,
        asset,
        character,
        location,
        world,
        database,
        innate_treasure_service(data, database),
    )
    interaction.initialize()
    feature = TongquetaiFeature(
        data,
        transfer,
        character,
        companion,
        asset,
        player_state,
        location,
        world,
        database,
        innate_treasure_service(data, database),
    )
    feature.initialize()
    return growth, database, world, location, asset, companion, character, create, interaction, feature


def _grant(database, asset, item_id: str, grade_id: str, quantity: int, request_id: str):
    plan = _run(
        asset.plan_inventory_changes(
            "qq-1", (InventoryAdjustment(item_id, grade_id, quantity),)
        )
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1", request_id, "测试入库", plan.operations, {"物品": item_id}
            )
        )
    )


def _prepare(tmp_path: Path, *, with_medicine: bool):
    services = _services(tmp_path)
    growth, database, world, location, asset, companion, _, create, interaction, _ = services
    _run(create.create(CreateCharacterRequest("qq-1", "create", "林远", "男")))
    birthplace = world.map_view().birthplace
    definition = next(
        companion.definition(value.companion_id)
        for value in companion.local_cultivators(birthplace)
        if value.gender == "女"
    )
    gift_id = min(definition.favorite_item_ids)
    _grant(database, asset, gift_id, "02", 10, "gift-stock")
    _run(
        interaction.gift(
            CompanionGiftRequest(
                "qq-1", "gift", definition.companion_id, gift_id, "02", 10
            )
        )
    )
    invited = _run(
        interaction.invite(
            CompanionInvitationRequest("qq-1", "invite", definition.companion_id)
        )
    )
    growth_plan = _run(
        companion.plan_growth(
            "qq-1",
            experience=sum(growth.experience_required(level) for level in range(1, 6)),
        )
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1", "grow", "测试成长", growth_plan.operations, {"等级": 5}
            )
        )
    )
    breakthrough = _run(companion.plan_breakthrough("qq-1", medicine_id="140002"))
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "breakthrough",
                "测试突破",
                breakthrough.operations,
                {"境界": breakthrough.realm_after},
            )
        )
    )
    if with_medicine:
        _grant(database, asset, "160003", "01", 1, "medicine-stock")
    origin = _run(location.current("qq-1"))
    destination = world.locate(LocationQuery(location_name="铜雀台"))
    _run(
        location.move(
            LocationMoveCommand(
                "qq-1", "travel", origin.xy, destination.xy
            )
        )
    )
    return services, definition, invited.instance


def test_protected_transfer_keeps_relation_and_build(tmp_path: Path) -> None:
    services, definition, initial = _prepare(tmp_path, with_medicine=True)
    _, _, _, _, asset, companion, _, _, _, feature = services
    before = _run(companion.active_instance("qq-1")).instance
    relation_before = _run(companion.relation("qq-1", definition.companion_id))

    preview = _run(feature.preview("qq-1"))
    assert preview.has_medicine is True
    assert preview.protected.offered > preview.severed.offered
    settled = _run(feature.settle(TongquetaiRequest("qq-1", "transfer", "护契")))

    assert settled.mode == "护契"
    assert settled.accepted == preview.protected.accepted
    after = _run(companion.active_instance("qq-1")).instance
    relation_after = _run(companion.relation("qq-1", definition.companion_id))
    assert (after.level, after.experience) == (1, 0)
    assert after.realm_id == initial.realm_id
    assert after.attributes == initial.attributes
    assert after.cultivation == before.cultivation
    assert after.weapon_name == before.weapon_name
    assert after.weapon_level == before.weapon_level
    assert after.weapon_laws == before.weapon_laws
    assert before.breakthrough_records
    assert after.breakthrough_records == ()
    assert after.qualification == before.qualification
    assert after.attribute_multipliers == before.attribute_multipliers
    assert relation_after.current_affection == relation_before.current_affection
    assert not _run(asset.inventory_stacks("qq-1", "160003"))


def test_severed_transfer_keeps_history_but_clears_affection_and_active(
    tmp_path: Path,
) -> None:
    services, definition, initial = _prepare(tmp_path, with_medicine=False)
    _, _, _, _, _, companion, _, _, _, feature = services
    relation_before = _run(companion.relation("qq-1", definition.companion_id))

    settled = _run(feature.settle(TongquetaiRequest("qq-1", "transfer", "离契")))

    assert settled.mode == "离契"
    assert _run(companion.active("qq-1")) is None
    instance = _run(companion.instance("qq-1", definition.companion_id))
    relation_after = _run(companion.relation("qq-1", definition.companion_id))
    assert instance is not None
    assert (instance.level, instance.experience) == (1, 0)
    assert instance.realm_id == initial.realm_id
    assert instance.attributes == initial.attributes
    assert instance.breakthrough_records == ()
    assert relation_after.current_affection == 0
    assert relation_after.gift_totals == relation_before.gift_totals
    assert relation_after.first_full_at == relation_before.first_full_at
    assert relation_after.first_invited_at == relation_before.first_invited_at
