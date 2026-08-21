"""统一解释异步玩法已经保存的时间和阶段事实。"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from .contracts import (
    ACTIVITY_PHASES,
    ActivityFacts,
    ActivityLifecycle,
    ActivityLifecycleStatus,
)


class ActivityLifecycleService:
    """只计算公共生命周期，不拥有任何玩法状态。"""

    def __init__(self) -> None:
        self._initialized = False

    def initialize(self) -> ActivityLifecycleStatus:
        if self._initialized:
            raise RuntimeError("异步玩法生命周期核心已经初始化")
        self._initialized = True
        return self.status()

    def status(self) -> ActivityLifecycleStatus:
        return ActivityLifecycleStatus(self._initialized)

    def view(
        self,
        facts: ActivityFacts,
        viewer_user_id: str,
        *,
        now: datetime | None = None,
    ) -> ActivityLifecycle:
        if not self._initialized:
            raise RuntimeError("异步玩法生命周期核心尚未初始化")
        activity_type = _text(facts.activity_type, "玩法类型")
        activity_id = _text(facts.activity_id, "玩法编号")
        owner = _text(facts.owner_id, "归属编号")
        participants = _users(
            facts.participant_user_ids,
            "参与用户",
            allow_empty=True,
        )
        settlers = _users(
            facts.settlement_user_ids,
            "结算用户",
            allow_empty=True,
        )
        phase = _text(facts.phase, "玩法阶段")
        if phase not in ACTIVITY_PHASES - {"ready"}:
            raise ValueError(f"玩法阶段无效：{phase}")
        started_at = _time(facts.started_at, "开始时间")
        ends_at = _time(facts.ends_at, "结束时间")
        completed_at = _time(facts.completed_at, "完成时间")
        current = _time(now or datetime.now(UTC), "当前时间")
        if phase == "running":
            if started_at is None or ends_at is None:
                raise ValueError("进行中的异步玩法必须保存开始时间和结束时间")
            if ends_at < started_at:
                raise ValueError("异步玩法结束时间不能早于开始时间")
            if current >= ends_at:
                phase = "ready"
        if phase in {"settled", "terminated"} and completed_at is None:
            raise ValueError("终态异步玩法必须保存完成时间")
        remaining = (
            max(0, math.ceil((ends_at - current).total_seconds()))
            if phase == "running" and ends_at is not None
            else 0
        )
        viewer = _text(viewer_user_id, "查看用户")
        can_settle = viewer in settlers and (
            phase == "ready" or (phase == "running" and facts.early_settlement)
        )
        return ActivityLifecycle(
            activity_type,
            activity_id,
            owner,
            participants,
            phase,
            started_at,
            ends_at,
            completed_at,
            remaining,
            can_settle,
        )


def _text(value: object, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label}不能为空")
    return normalized


def _users(values: tuple[str, ...], label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    normalized = tuple(_text(value, label) for value in values)
    if not normalized and not allow_empty:
        raise ValueError(f"{label}不能为空")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label}不能重复")
    return normalized


def _time(value: datetime | None, label: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}必须包含时区")
    return value.astimezone(UTC)


__all__ = ["ActivityLifecycleService"]
