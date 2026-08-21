from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from game.core.activity import ActivityFacts, ActivityLifecycleService
from game.core.database import SettlementTransactionPlan, StateMutation


def _mutation(state_type: str) -> StateMutation:
    return StateMutation("qq-1", state_type, "main", {}, 0)


def test_lifecycle_interprets_time_without_owning_session_state() -> None:
    service = ActivityLifecycleService()
    service.initialize()
    started = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
    facts = ActivityFacts(
        "探险",
        "activity-1",
        "qq-1",
        ("qq-1", "qq-2"),
        ("qq-1",),
        "running",
        started,
        started + timedelta(minutes=30),
    )

    running = service.view(facts, "qq-1", now=started + timedelta(minutes=10))
    assert running.phase == "running"
    assert running.remaining_seconds == 1200
    assert running.can_settle is False

    ready = service.view(facts, "qq-1", now=started + timedelta(minutes=30))
    assert ready.phase == "ready"
    assert ready.remaining_seconds == 0
    assert ready.can_settle is True
    assert service.view(facts, "qq-2", now=ready.ends_at).can_settle is False


def test_settlement_plan_requires_results_release_and_record() -> None:
    with pytest.raises(ValueError, match="释放"):
        SettlementTransactionPlan(
            result_operations=(_mutation("character"),),
            reward_operations=(),
            release_operations=(),
            record_operations=(_mutation("settlement"),),
        ).command(
            user_id="qq-1",
            request_id="settle-1",
            business_type="测试结算",
            payload={},
        )

    command = SettlementTransactionPlan(
        result_operations=(_mutation("character"),),
        reward_operations=(_mutation("inventory"),),
        release_operations=(_mutation("player_state"),),
        record_operations=(_mutation("settlement"),),
    ).command(
        user_id="qq-1",
        request_id="settle-2",
        business_type="测试结算",
        payload={"玩法编号": "activity-1"},
    )
    assert tuple(value.state_type for value in command.operations) == (
        "character",
        "inventory",
        "player_state",
        "settlement",
    )
