from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.data import JsonDataService
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateMutation,
    TransactionCommand,
)
from game.core.player_state import (
    PlayerStateConflictError,
    PlayerStateRuleError,
    PlayerStateService,
    StateTransitionCommand,
)


def _run(awaitable):
    return asyncio.run(awaitable)


def _service(tmp_path: Path) -> tuple[PlayerStateService, DatabaseService]:
    root = Path(__file__).resolve().parents[3]
    data = JsonDataService(root / "data")
    data.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    _run(
        database.commit(
            TransactionCommand(
                user_id="qq-1",
                request_id="create-1",
                business_type="创建人物",
                mutations=(
                    StateMutation("character", "main", {"姓名": "林远"}, 0),
                    player_state.initial_mutation(),
                ),
                payload={},
            )
        )
    )
    return player_state, database


def test_initial_snapshot_contains_three_independent_slots(tmp_path: Path) -> None:
    player_state, database = _service(tmp_path)

    current = _run(player_state.current("qq-1"))

    assert player_state.status().state_count == 10
    assert player_state.status().guard_rule_count == 7
    assert current is not None
    assert {key: value.state_id for key, value in current.states.items()} == {
        "行为": "520001",
        "队伍": "520007",
        "控制": "520009",
    }
    snapshot = _run(database.get(StateAddress("qq-1", "player_state", "main")))
    assert snapshot is not None
    assert set(snapshot.value) == {"行为", "队伍", "控制"}


def test_guard_requires_all_declared_types_but_ors_within_type(tmp_path: Path) -> None:
    player_state, _ = _service(tmp_path)

    allowed = _run(player_state.authorize("qq-1", "自主空闲或休息"))
    assert allowed.allowed is True

    _run(
        player_state.transition(
            StateTransitionCommand("qq-1", "travel-1", "行为", "520003")
        )
    )
    blocked = _run(player_state.authorize("qq-1", "自主空闲或休息"))
    assert blocked.allowed is False
    assert "行为为行路中" in blocked.reason


def test_state_transition_uses_json_edges_and_versions(tmp_path: Path) -> None:
    player_state, _ = _service(tmp_path)

    entered = _run(
        player_state.transition(
            StateTransitionCommand("qq-1", "team-1", "队伍", "520008")
        )
    )
    assert (entered.previous_state_id, entered.current_state_id, entered.version) == (
        "520007",
        "520008",
        2,
    )
    with pytest.raises(PlayerStateConflictError):
        _run(
            player_state.transition(
                StateTransitionCommand("qq-1", "team-2", "队伍", "520008")
            )
        )


def test_guard_character_requirement_and_unknown_rule_fail_closed(
    tmp_path: Path,
) -> None:
    player_state, database = _service(tmp_path)

    assert _run(player_state.authorize("qq-1", "仅未创建")).allowed is False
    with pytest.raises(PlayerStateRuleError):
        _run(player_state.authorize("qq-1", "不存在"))
    with pytest.raises(PlayerStateRuleError):
        player_state.validate_guard_rule("不存在")

    database.close()
    with pytest.raises(RuntimeError):
        _run(player_state.current("qq-1"))
