from __future__ import annotations

import asyncio
import sqlite3

import pytest

from game.core.database import (
    DatabaseService,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)


def _run(awaitable):
    return asyncio.run(awaitable)


def _command(
    *,
    request_id: str,
    mutations: tuple[StateMutation, ...],
    payload: dict[str, object] | None = None,
) -> TransactionCommand:
    return TransactionCommand(
        user_id="10001",
        request_id=request_id,
        business_type="测试结算",
        mutations=mutations,
        payload=payload or {},
    )


def test_database_has_only_two_business_tables(tmp_path) -> None:
    path = tmp_path / "game.db"
    service = DatabaseService(path)

    status = service.initialize()

    assert status.state_count == 0
    assert status.transaction_count == 0
    with sqlite3.connect(path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert tables == {"state_snapshot", "committed_transaction"}


def test_commit_writes_multiple_states_atomically(tmp_path) -> None:
    service = DatabaseService(tmp_path / "game.db")
    service.initialize()
    command = _command(
        request_id="event-1",
        mutations=(
            StateMutation("character", "main", {"等级": 1, "灵石": 10000}, 0),
            StateMutation("inventory", "丹药:100005:01", {"数量": 3}, 0),
        ),
        payload={"来源": "创建人物"},
    )

    receipt = _run(service.commit(command))
    character = _run(service.get(StateAddress("10001", "character", "main")))
    inventory = _run(
        service.get(StateAddress("10001", "inventory", "丹药:100005:01"))
    )

    assert receipt.replayed is False
    assert [change.operation for change in receipt.changes] == ["insert", "insert"]
    assert character is not None and character.value == {"等级": 1, "灵石": 10000}
    assert inventory is not None and inventory.value == {"数量": 3}
    assert character.version == inventory.version == 1


def test_returned_snapshot_is_recursively_read_only(tmp_path) -> None:
    service = DatabaseService(tmp_path / "game.db")
    service.initialize()
    _run(
        service.commit(
            _command(
                request_id="event-read-only",
                mutations=(
                    StateMutation(
                        "character",
                        "main",
                        {"属性": {"攻击": 12}, "功法": ["310001"]},
                        0,
                    ),
                ),
            )
        )
    )

    snapshot = _run(service.get(StateAddress("10001", "character", "main")))

    assert snapshot is not None
    with pytest.raises(TypeError):
        snapshot.value["属性"] = {}  # type: ignore[index]
    attributes = snapshot.value["属性"]
    assert isinstance(attributes, dict) is False
    with pytest.raises(TypeError):
        attributes["攻击"] = 99  # type: ignore[index]
    assert snapshot.value["功法"] == ("310001",)


def test_same_request_is_replayed_without_second_write(tmp_path) -> None:
    service = DatabaseService(tmp_path / "game.db")
    service.initialize()
    command = _command(
        request_id="event-2",
        mutations=(StateMutation("character", "main", {"等级": 1}, 0),),
    )

    first = _run(service.commit(command))
    second = _run(service.commit(command))
    snapshot = _run(service.get(StateAddress("10001", "character", "main")))

    assert second.transaction_id == first.transaction_id
    assert second.replayed is True
    assert snapshot is not None and snapshot.version == 1
    assert service.status().transaction_count == 1


def test_version_conflict_rolls_back_every_mutation(tmp_path) -> None:
    service = DatabaseService(tmp_path / "game.db")
    service.initialize()
    _run(
        service.commit(
            _command(
                request_id="event-3",
                mutations=(
                    StateMutation("character", "main", {"灵石": 10000}, 0),
                    StateMutation("inventory", "丹药:100005:01", {"数量": 3}, 0),
                ),
            )
        )
    )

    conflict = _command(
        request_id="event-4",
        mutations=(
            StateMutation("character", "main", {"灵石": 9000}, 1),
            StateMutation("inventory", "丹药:100005:01", {"数量": 4}, 0),
        ),
    )
    with pytest.raises(StateConflictError):
        _run(service.commit(conflict))

    character = _run(service.get(StateAddress("10001", "character", "main")))
    inventory = _run(
        service.get(StateAddress("10001", "inventory", "丹药:100005:01"))
    )
    assert character is not None and character.value == {"灵石": 10000}
    assert inventory is not None and inventory.value == {"数量": 3}
    assert service.status().transaction_count == 1
