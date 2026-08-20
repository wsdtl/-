from __future__ import annotations

import asyncio

import pytest

import game.app as game_app
from game.config import GameConfig, GameDatabaseConfig
from game.core.asset import CultivationAcquisition, InventoryAdjustment
from game.core.database import TransactionCommand
from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.zongmen import SectFeatureError


def _run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setattr(
        game_app,
        "game_config",
        GameConfig(
            GameDatabaseConfig(
                tmp_path / "game.db",
                tmp_path / "runtime.db",
                5000,
            )
        ),
    )
    value = game_app.build_game_services()
    yield value
    value.core.database.close()


def _create_sect(services) -> None:
    create = services.features.chuangjian_renwu
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    _run(create.create(CreateCharacterRequest("qq-2", "create-2", "白川", "男")))
    sect = services.features.zongmen
    _run(sect.create("qq-1", "sect-create", "青云宗"))
    _run(sect.invite("qq-1", "白川", "sect-invite"))
    _run(sect.accept("qq-2", "sect-accept"))
    _run(services.features.zongmen_shanmen.enter("qq-1", "gate-enter-1"))
    _run(services.features.zongmen_shanmen.enter("qq-2", "gate-enter-2"))


def _commit(services, user_id: str, request_id: str, operations) -> None:
    _run(
        services.core.database.commit(
            TransactionCommand(user_id, request_id, "测试准备", tuple(operations), {})
        )
    )


def test_lingcang_and_wanzhen_transfer_real_personal_assets(services) -> None:
    _create_sect(services)
    data = services.core.data
    herb_id = next(
        content_id
        for content_id in data.entities("物品")
        if data.entity_record("物品", content_id).number_category == "灵植"
    )
    herb_plan = _run(
        services.core.asset.plan_inventory_changes(
            "qq-1", (InventoryAdjustment(herb_id, "01", 3),)
        )
    )
    stones_before = _run(services.core.character.profile("qq-1")).spirit_stones
    stone_plan = _run(
        services.core.character.plan_spirit_stone_change("qq-1", delta=100)
    )
    _commit(
        services,
        "qq-1",
        "prepare-lingcang",
        (*herb_plan.operations, stone_plan.operation),
    )

    _run(
        services.features.zongmen_lingcang.donate_material(
            "qq-1", "donate-herb", "灵植", herb_id, "01", 2
        )
    )
    _run(services.features.zongmen_lingcang.donate_stones("qq-1", "donate-stones", 40))
    lingcang = _run(services.features.zongmen_lingcang.page("qq-1", "灵植"))
    assert lingcang.spirit_stones == 40
    assert [(value.content_id, value.quantity) for value in lingcang.entries] == [
        (herb_id, 2)
    ]
    assert _run(services.core.asset.inventory_stacks("qq-1", herb_id))[0].quantity == 1
    assert (
        _run(services.core.character.profile("qq-1")).spirit_stones
        == stones_before + 60
    )

    medicine_id = next(
        content_id
        for content_id in data.entities("物品")
        if data.entity_record("物品", content_id).number_category == "丹药"
    )
    medicine_plan = _run(
        services.core.asset.plan_inventory_changes(
            "qq-1", (InventoryAdjustment(medicine_id, "01", 1),)
        )
    )
    _commit(services, "qq-1", "prepare-wanzhen", medicine_plan.operations)
    donated = _run(
        services.features.zongmen_wanzhen.donate(
            "qq-1", "donate-medicine", "丹药", medicine_id, "01", 1
        )
    )
    granted = _run(
        services.features.zongmen_wanzhen.grant(
            "qq-1", "grant-medicine", "白川", donated.entry.entry_key, 1
        )
    )
    assert granted.target_name == "白川"
    assert (
        _run(services.core.asset.inventory_stacks("qq-2", medicine_id))[0].quantity >= 1
    )

    with pytest.raises(SectFeatureError, match="storage_not_empty"):
        _run(services.features.zongmen.disband("qq-1", "sect-disband"))


def test_cangjing_uses_highest_grade_and_invalidates_borrowing_after_kick(
    services,
) -> None:
    _create_sect(services)
    technique_id = next(iter(services.core.data.entities("功法")))
    low = _run(
        services.core.asset.plan_cultivation_acquisitions(
            "qq-1", (CultivationAcquisition("功法", technique_id, "01"),)
        )
    )
    high = _run(
        services.core.asset.plan_cultivation_acquisitions(
            "qq-2", (CultivationAcquisition("功法", technique_id, "03"),)
        )
    )
    _commit(services, "qq-1", "prepare-technique-low", low.operations)
    _commit(services, "qq-2", "prepare-technique-high", high.operations)

    page = _run(services.features.zongmen_cangjing.page("qq-2"))
    technique = next(
        value for value in page.entries if value.content_id == technique_id
    )
    assert technique.grade_id == "03"
    _run(
        services.features.zongmen_cangjing.borrow(
            "qq-2", "borrow-technique", technique_id, 1
        )
    )
    equipped = _run(services.core.character.profile("qq-2")).equipped_content
    assert any(
        value.category == "功法"
        and value.content_id == technique_id
        and value.grade == "03"
        for value in equipped
    )

    _run(services.features.zongmen.kick("qq-1", "白川", "sect-kick"))
    equipped_after = _run(services.core.character.profile("qq-2")).equipped_content
    assert all(value.content_id != technique_id for value in equipped_after)
