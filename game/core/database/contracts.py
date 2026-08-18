"""核心数据库微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DatabaseError(RuntimeError):
    """数据库服务无法完成请求。"""


class StateConflictError(DatabaseError):
    """状态版本与调用方预期不一致。"""


class IdempotencyConflictError(DatabaseError):
    """同一请求编号被重复用于不同事务。"""


JsonObject = Mapping[str, Any]


@dataclass(frozen=True)
class DatabaseStatus:
    initialized: bool
    path: Path
    state_count: int
    location_count: int
    transaction_count: int


@dataclass(frozen=True)
class StateAddress:
    user_id: str
    state_type: str
    state_key: str


@dataclass(frozen=True)
class StateSnapshot:
    address: StateAddress
    value: JsonObject
    version: int
    updated_at: str


@dataclass(frozen=True)
class StateMutation:
    user_id: str
    state_type: str
    state_key: str
    value: JsonObject | None
    expected_version: int


@dataclass(frozen=True)
class LocationMutation:
    user_id: str
    xy: tuple[int, int] | None
    expected_version: int


@dataclass(frozen=True)
class StateChange:
    user_id: str
    state_type: str
    state_key: str
    operation: str
    before_version: int | None
    after_version: int | None


@dataclass(frozen=True)
class TransactionCommand:
    user_id: str
    request_id: str
    business_type: str
    operations: tuple[StateMutation | LocationMutation, ...]
    payload: JsonObject


@dataclass(frozen=True)
class TransactionReceipt:
    transaction_id: str
    user_id: str
    request_id: str
    business_type: str
    committed_at: str
    replayed: bool
    changes: tuple[StateChange, ...]


@dataclass(frozen=True)
class CommittedTransaction:
    receipt: TransactionReceipt
    payload: JsonObject


@dataclass(frozen=True)
class LocationRecord:
    user_id: str
    xy: tuple[int, int]
    version: int
    updated_at: str


@dataclass(frozen=True)
class NearbyLocationRecord:
    user_id: str
    xy: tuple[int, int]
    horizontal_distance_squared_meters: int


__all__ = [
    "CommittedTransaction",
    "DatabaseError",
    "DatabaseStatus",
    "IdempotencyConflictError",
    "LocationMutation",
    "LocationRecord",
    "NearbyLocationRecord",
    "StateAddress",
    "StateChange",
    "StateConflictError",
    "StateMutation",
    "StateSnapshot",
    "TransactionCommand",
    "TransactionReceipt",
]
