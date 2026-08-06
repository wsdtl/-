from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.activity import (
    ActivityConflictError,
    ActivityService,
    ActivityTransitionCommand,
)
from game.core.data import JsonDataService
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateConflictError,
    TransactionCommand,
)


def _run(awaitable):
    return asyncio.run(awaitable)


def _service(tmp_path: Path) -> tuple[ActivityService, DatabaseService]:
    root = Path(__file__).resolve().parents[3]
    data = JsonDataService(root / "data")
    data.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    activity = ActivityService(data, database)
    activity.initialize()
    _run(
        database.commit(
            TransactionCommand(
                user_id="qq-1",
                request_id="create-1",
                business_type="创建人物",
                mutations=(activity.initial_mutation(),),
                payload={},
            )
        )
    )
    return activity, database


def test_activity_loads_json_rules_and_initial_state(tmp_path: Path) -> None:
    activity, _ = _service(tmp_path)

    status = activity.status()
    current = _run(activity.current("qq-1"))

    assert status.status_count == 5
    assert status.access_rule_count == 3
    assert current is not None
    assert current.name == "空闲"
    assert current.version == 1


def test_enter_and_finish_are_persisted_as_one_state(tmp_path: Path) -> None:
    activity, database = _service(tmp_path)

    entered = _run(
        activity.enter(
            ActivityTransitionCommand(
                "qq-1",
                "travel-1",
                "行路",
                {"目的地": "天衡城"},
            )
        )
    )
    assert (entered.previous, entered.current, entered.version) == ("空闲", "行路", 2)

    finished = _run(activity.finish("qq-1", "travel-2"))
    assert (finished.previous, finished.current, finished.version) == ("行路", "空闲", 3)
    snapshot = _run(database.get(StateAddress("qq-1", "character_status", "main")))
    assert snapshot is not None
    assert snapshot.value == {"名称": "空闲", "上下文": {}}


def test_busy_state_blocks_idle_only_access_and_disallows_invalid_transition(
    tmp_path: Path,
) -> None:
    activity, _ = _service(tmp_path)
    _run(activity.enter(ActivityTransitionCommand("qq-1", "travel-1", "行路")))

    access = _run(activity.authorize("qq-1", "仅空闲"))
    assert access.allowed is False
    assert access.current == "行路"
    assert _run(activity.authorize("qq-1", "不受限制")).allowed is True
    with pytest.raises(ActivityConflictError):
        _run(activity.enter(ActivityTransitionCommand("qq-1", "bad-1", "闭关")))


def test_interrupt_uses_json_interrupt_rule(tmp_path: Path) -> None:
    activity, _ = _service(tmp_path)
    _run(activity.enter(ActivityTransitionCommand("qq-1", "travel-1", "行路")))
    interrupted = _run(activity.interrupt("qq-1", "travel-stop"))
    assert (interrupted.previous, interrupted.current) == ("行路", "空闲")

    _run(activity.enter(ActivityTransitionCommand("qq-1", "retreat-1", "闭关")))
    with pytest.raises(ActivityConflictError):
        _run(activity.interrupt("qq-1", "retreat-stop"))


def test_stale_transition_rolls_back_without_changing_status(tmp_path: Path) -> None:
    activity, database = _service(tmp_path)

    with pytest.raises(StateConflictError):
        _run(
            activity.enter(
                ActivityTransitionCommand(
                    "qq-1",
                    "stale-1",
                    "行路",
                    expected_version=0,
                )
            )
        )
    current = _run(activity.current("qq-1"))
    assert current is not None and current.name == "空闲" and current.version == 1
    assert database.status().transaction_count == 1
