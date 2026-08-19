from __future__ import annotations

import asyncio
import sqlite3

import pytest

from game.core.database import (
    DatabaseService,
    LocationMutation,
    SharedConstraintError,
    SharedEntityMutation,
    SharedLocationMutation,
    SharedMemberMutation,
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
    operations: tuple[StateMutation | LocationMutation, ...],
    payload: dict[str, object] | None = None,
) -> TransactionCommand:
    return TransactionCommand(
        user_id="10001",
        request_id=request_id,
        business_type="测试结算",
        operations=operations,
        payload=payload or {},
    )


def test_database_has_state_transaction_and_location_tables(tmp_path) -> None:
    path = tmp_path / "game.db"
    service = DatabaseService(path)

    status = service.initialize()

    assert status.state_count == 0
    assert status.location_count == 0
    assert status.transaction_count == 0
    with sqlite3.connect(path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert tables == {
        "state_snapshot",
        "committed_transaction",
        "player_location",
        "player_space",
        "shared_entity",
        "shared_member",
        "shared_location",
    }


def test_shared_entities_members_and_locations_are_atomic_and_unique(tmp_path) -> None:
    service = DatabaseService(tmp_path / "game.db")
    service.initialize()
    receipt = _run(
        service.commit(
            _command(
                request_id="sect-create",
                operations=(
                    SharedEntityMutation(
                        "宗门",
                        "sect-1",
                        {
                            "编号": "sect-1",
                            "名称": "青云宗",
                            "宗主": "10001",
                            "洞天编号": "cave-1",
                            "入口坐标": [10, 20],
                        },
                        0,
                    ),
                    SharedMemberMutation("宗门", "10001", "sect-1", "宗主", 1, 0),
                    SharedLocationMutation("宗门", "sect-1", (10, 20), 0),
                ),
            )
        )
    )
    assert receipt.replayed is False
    entity = _run(service.get_shared_entity("宗门", "sect-1"))
    member = _run(service.get_shared_member("宗门", "10001"))
    location = _run(service.get_shared_location("宗门", "sect-1"))
    assert entity is not None and entity.value["名称"] == "青云宗"
    assert member is not None and member.role == "宗主"
    assert location is not None and location.xy == (10, 20)

    with pytest.raises(SharedConstraintError):
        _run(
            service.commit(
                _command(
                    request_id="sect-duplicate-location",
                    operations=(
                        SharedEntityMutation(
                            "宗门",
                            "sect-2",
                            {
                                "编号": "sect-2",
                                "名称": "赤霄宗",
                                "宗主": "10002",
                                "洞天编号": "cave-2",
                                "入口坐标": [10, 20],
                            },
                            0,
                        ),
                        SharedMemberMutation("宗门", "10002", "sect-2", "宗主", 1, 0),
                        SharedLocationMutation("宗门", "sect-2", (10, 20), 0),
                    ),
                )
            )
        )
    assert _run(service.get_shared_entity("宗门", "sect-2")) is None
    assert _run(service.get_shared_member("宗门", "10002")) is None


def test_commit_writes_multiple_states_atomically(tmp_path) -> None:
    service = DatabaseService(tmp_path / "game.db")
    service.initialize()
    command = _command(
        request_id="event-1",
        operations=(
            StateMutation(
                "10001",
                "character",
                "main",
                {"等级": 1, "灵石": 10000, "属性": {"攻击": 12}, "功法": ["310001"]},
                0,
            ),
            StateMutation("10001", "inventory", "100005:01", {"数量": 3}, 0),
        ),
        payload={"来源": "创建人物"},
    )

    receipt = _run(service.commit(command))
    character = _run(service.get(StateAddress("10001", "character", "main")))
    inventory = _run(service.get(StateAddress("10001", "inventory", "100005:01")))

    assert receipt.replayed is False
    assert [change.operation for change in receipt.changes] == ["insert", "insert"]
    assert character is not None
    assert character.value == {
        "等级": 1,
        "灵石": 10000,
        "属性": {"攻击": 12},
        "功法": ("310001",),
    }
    assert inventory is not None and inventory.value == {"数量": 3}
    assert character.version == inventory.version == 1
    with pytest.raises(TypeError):
        character.value["属性"] = {}  # type: ignore[index]
    attributes = character.value["属性"]
    assert isinstance(attributes, dict) is False
    with pytest.raises(TypeError):
        attributes["攻击"] = 99  # type: ignore[index]


def test_same_request_is_replayed_without_second_write(tmp_path) -> None:
    service = DatabaseService(tmp_path / "game.db")
    service.initialize()
    command = _command(
        request_id="event-2",
        operations=(StateMutation("10001", "character", "main", {"等级": 1}, 0),),
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
                operations=(
                    StateMutation("10001", "character", "main", {"灵石": 10000}, 0),
                    StateMutation("10001", "inventory", "100005:01", {"数量": 3}, 0),
                ),
            )
        )
    )

    conflict = _command(
        request_id="event-4",
        operations=(
            StateMutation("10001", "character", "main", {"灵石": 9000}, 1),
            StateMutation("10001", "inventory", "100005:01", {"数量": 4}, 0),
        ),
    )
    with pytest.raises(StateConflictError):
        _run(service.commit(conflict))

    character = _run(service.get(StateAddress("10001", "character", "main")))
    inventory = _run(service.get(StateAddress("10001", "inventory", "100005:01")))
    assert character is not None and character.value == {"灵石": 10000}
    assert inventory is not None and inventory.value == {"数量": 3}
    assert service.status().transaction_count == 1
