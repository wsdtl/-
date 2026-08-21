from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.data import JsonDataService
from game.core.database import DatabaseService, StateMutation, TransactionCommand
from game.core.innate_treasure import InnateTreasureError, InnateTreasureService


def _run(awaitable):
    return asyncio.run(awaitable)


def _service(tmp_path: Path) -> tuple[InnateTreasureService, DatabaseService]:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    service = InnateTreasureService(data, database)
    service.initialize()
    return service, database


def _commit(database: DatabaseService, request_id: str, operation: StateMutation) -> None:
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                request_id,
                "测试先天灵宝",
                (operation,),
                {},
            )
        )
    )


def test_loads_twenty_one_non_location_treasures(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    treasures = service.treasures()

    assert len(treasures) == 21
    assert all("位置" not in value.effect.node for value in treasures)
    assert all("附近" not in value.effect.node for value in treasures)
    assert service.resolve("太初万药鼎").treasure_id == "540001"


def test_acquire_is_permanent_idempotent_and_equip_is_single_slot(tmp_path: Path) -> None:
    service, database = _service(tmp_path)

    assert _run(service.collection("qq-1")).owned == ()
    first = _run(service.plan_acquire("qq-1", "540001"))
    assert first.operation is not None
    _commit(database, "acquire-1", first.operation)
    duplicate = _run(service.plan_acquire("qq-1", "540001"))
    assert duplicate.already_owned is True
    assert duplicate.operation is None

    second = _run(service.plan_acquire("qq-1", "540002"))
    assert second.operation is not None
    _commit(database, "acquire-2", second.operation)
    equip_first = _run(service.plan_equip("qq-1", "太初万药鼎"))
    assert equip_first.operation is not None
    _commit(database, "equip-1", equip_first.operation)
    equip_second = _run(service.plan_equip("qq-1", "540002"))
    assert equip_second.operation is not None
    _commit(database, "equip-2", equip_second.operation)

    collection = _run(service.collection("qq-1"))
    assert [value.treasure_id for value in collection.owned] == ["540001", "540002"]
    assert collection.active is not None
    assert collection.active.treasure_id == "540002"
    assert _run(service.effect("qq-1", "炼器成功")) is not None
    assert _run(service.effect("qq-1", "炼丹成功")) is None
    assert service.effect_for("540001", "炼丹成功") is not None
    assert service.effect_for("540001", "闭关开始") is None


def test_cannot_equip_unowned_or_accept_invalid_state(tmp_path: Path) -> None:
    service, database = _service(tmp_path)

    with pytest.raises(InnateTreasureError, match="没有这件"):
        _run(service.plan_equip("qq-1", "540001"))

    _commit(
        database,
        "invalid-state",
        StateMutation(
            "qq-1",
            "innate_treasure",
            "main",
            {"已获得": ["540001"], "当前执掌": "540002"},
            0,
        ),
    )
    with pytest.raises(InnateTreasureError, match="不在灵宝谱中"):
        _run(service.collection("qq-1"))
