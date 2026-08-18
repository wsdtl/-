"""核心数据库的 SQLite 内部实现；不属于跨服务公共接口。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from uuid import uuid4

from .contracts import (
    CommittedTransaction,
    DatabaseError,
    IdempotencyConflictError,
    LocationMutation,
    LocationRecord,
    NearbyLocationRecord,
    StateAddress,
    StateChange,
    StateConflictError,
    StateMutation,
    StateSnapshot,
    TransactionCommand,
    TransactionReceipt,
)


class SQLiteStateStore:
    """玩家状态、位置与幂等事务的 SQLite 仓储。"""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._write_lock = RLock()
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("核心数据库已经初始化")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS state_snapshot (
                    user_id TEXT NOT NULL,
                    state_type TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, state_type, state_key)
                );
                CREATE TABLE IF NOT EXISTS committed_transaction (
                    transaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    business_type TEXT NOT NULL,
                    changes_json TEXT NOT NULL,
                    committed_at TEXT NOT NULL,
                    UNIQUE (user_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS player_location (
                    user_id TEXT PRIMARY KEY,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_state_snapshot_user
                ON state_snapshot(user_id, state_type);
                CREATE INDEX IF NOT EXISTS ix_committed_transaction_user
                ON committed_transaction(user_id, committed_at);
                CREATE INDEX IF NOT EXISTS ix_player_location_xy
                ON player_location(x, y, user_id);
                """
            )
        self._initialized = True

    def counts(self) -> tuple[int, int, int]:
        self._require_initialized()
        with self._connect() as connection:
            state_count = int(
                connection.execute("SELECT COUNT(*) FROM state_snapshot").fetchone()[0]
            )
            location_count = int(
                connection.execute("SELECT COUNT(*) FROM player_location").fetchone()[0]
            )
            transaction_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM committed_transaction"
                ).fetchone()[0]
            )
        return state_count, location_count, transaction_count

    def get(self, address: StateAddress) -> StateSnapshot | None:
        self._require_initialized()
        _validate_address(address)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT state_json, version, updated_at
                FROM state_snapshot
                WHERE user_id = ? AND state_type = ? AND state_key = ?
                """,
                (address.user_id, address.state_type, address.state_key),
            ).fetchone()
        return _snapshot(address, row) if row is not None else None

    def list_for_user(
        self, user_id: str, state_type: str | None = None
    ) -> tuple[StateSnapshot, ...]:
        self._require_initialized()
        _validate_text(user_id, "user_id")
        if state_type is not None:
            _validate_text(state_type, "state_type")
        query = (
            "SELECT state_type, state_key, state_json, version, updated_at "
            "FROM state_snapshot WHERE user_id = ?"
        )
        parameters: list[object] = [user_id]
        if state_type is not None:
            query += " AND state_type = ?"
            parameters.append(state_type)
        query += " ORDER BY state_type, state_key"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(
            _snapshot(
                StateAddress(user_id, str(row[0]), str(row[1])),
                row[2:],
            )
            for row in rows
        )

    def get_many(
        self, addresses: tuple[StateAddress, ...]
    ) -> tuple[StateSnapshot, ...]:
        self._require_initialized()
        if not addresses:
            return ()
        for address in addresses:
            _validate_address(address)
        if len(addresses) != len(
            {(item.user_id, item.state_type, item.state_key) for item in addresses}
        ):
            raise ValueError("批量状态地址不能重复")
        snapshots: dict[tuple[str, str, str], StateSnapshot] = {}
        with self._connect() as connection:
            for chunk in _chunks(addresses, 300):
                placeholders = ",".join("(?, ?, ?)" for _ in chunk)
                parameters = tuple(
                    value
                    for address in chunk
                    for value in (
                        address.user_id,
                        address.state_type,
                        address.state_key,
                    )
                )
                rows = connection.execute(
                    f"""
                    SELECT user_id, state_type, state_key, state_json, version, updated_at
                    FROM state_snapshot
                    WHERE (user_id, state_type, state_key) IN ({placeholders})
                    """,
                    parameters,
                ).fetchall()
                for row in rows:
                    key = (str(row[0]), str(row[1]), str(row[2]))
                    snapshots[key] = _snapshot(StateAddress(*key), row[3:])
        return tuple(
            snapshots[key]
            for address in addresses
            if (key := (address.user_id, address.state_type, address.state_key))
            in snapshots
        )

    def get_location(self, user_id: str) -> LocationRecord | None:
        self._require_initialized()
        _validate_text(user_id, "user_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT x, y, version, updated_at
                FROM player_location
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return LocationRecord(
            user_id, (int(row[0]), int(row[1])), int(row[2]), str(row[3])
        )

    def nearby_locations(
        self,
        *,
        origin_xy: tuple[int, int],
        radius_meters: int,
        cell_size_meters: int,
        limit: int,
        exclude_user_id: str,
    ) -> tuple[NearbyLocationRecord, ...]:
        self._require_initialized()
        origin_x, origin_y = _validate_xy(origin_xy)
        _validate_text(exclude_user_id, "exclude_user_id")
        for value, label in (
            (radius_meters, "radius_meters"),
            (cell_size_meters, "cell_size_meters"),
            (limit, "limit"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{label} 必须是正整数")
        cell_radius = (radius_meters + cell_size_meters - 1) // cell_size_meters
        radius_squared = radius_meters * radius_meters
        cells = sorted(
            (
                (
                    (dx * dx + dy * dy) * cell_size_meters * cell_size_meters,
                    origin_x + dx,
                    origin_y + dy,
                )
                for dx in range(-cell_radius, cell_radius + 1)
                for dy in range(-cell_radius, cell_radius + 1)
                if (dx * dx + dy * dy) * cell_size_meters * cell_size_meters
                <= radius_squared
            ),
            key=lambda value: (value[0], value[1], value[2]),
        )
        result: list[NearbyLocationRecord] = []
        with self._connect() as connection:
            for distance_squared, x, y in cells:
                remaining = limit - len(result)
                if remaining == 0:
                    break
                rows = connection.execute(
                    """
                    SELECT user_id
                    FROM player_location
                    WHERE x = ? AND y = ? AND user_id <> ?
                    ORDER BY user_id
                    LIMIT ?
                    """,
                    (x, y, exclude_user_id, remaining),
                ).fetchall()
                result.extend(
                    NearbyLocationRecord(
                        user_id=str(row[0]),
                        xy=(x, y),
                        horizontal_distance_squared_meters=distance_squared,
                    )
                    for row in rows
                )
        return tuple(result)

    def committed_transaction(
        self, user_id: str, request_id: str
    ) -> CommittedTransaction | None:
        """只读取得一次已经提交的幂等事务。"""

        self._require_initialized()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT transaction_id, business_type, changes_json, committed_at
                FROM committed_transaction
                WHERE user_id = ? AND request_id = ?
                """,
                (user_id, request_id),
            ).fetchone()
        if row is None:
            return None
        stored = json.loads(str(row[2]))
        payload = stored.get("payload")
        if not isinstance(payload, dict):
            raise DatabaseError("已提交事务缺少对象载荷")
        command = TransactionCommand(user_id, request_id, str(row[1]), (), {})
        return CommittedTransaction(
            _receipt_from_row(command, row, replayed=True),
            _freeze_json(payload),
        )

    def commit(self, command: TransactionCommand) -> TransactionReceipt:
        self._require_initialized()
        _validate_command(command)
        fingerprint = _command_json(command)
        transaction_id = uuid4().hex
        committed_at = _now()
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    """
                    SELECT transaction_id, business_type, changes_json, committed_at
                    FROM committed_transaction
                    WHERE user_id = ? AND request_id = ?
                    """,
                    (command.user_id, command.request_id),
                ).fetchone()
                if existing is not None:
                    stored = json.loads(str(existing[2]))
                    if stored.get("command") != fingerprint:
                        raise IdempotencyConflictError("request_id 已提交过不同事务")
                    connection.execute("COMMIT")
                    return _receipt_from_row(command, existing, replayed=True)

                changes: list[StateChange] = []
                for operation in command.operations:
                    if isinstance(operation, StateMutation):
                        changes.append(
                            _apply_mutation(connection, operation, committed_at)
                        )
                    else:
                        changes.append(
                            _apply_location_mutation(
                                connection, operation, committed_at
                            )
                        )
                changes_json = {
                    "command": fingerprint,
                    "payload": _json_value(command.payload),
                    "changes": [_change_json(change) for change in changes],
                }
                connection.execute(
                    """
                    INSERT INTO committed_transaction (
                        transaction_id, user_id, request_id, business_type,
                        changes_json, committed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        command.user_id,
                        command.request_id,
                        command.business_type,
                        _encode(changes_json),
                        committed_at,
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return TransactionReceipt(
            transaction_id=transaction_id,
            user_id=command.user_id,
            request_id=command.request_id,
            business_type=command.business_type,
            committed_at=committed_at,
            replayed=False,
            changes=tuple(changes),
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("核心数据库尚未初始化")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            yield connection
        finally:
            connection.close()


def _apply_mutation(
    connection: sqlite3.Connection,
    mutation: StateMutation,
    committed_at: str,
) -> StateChange:
    row = connection.execute(
        """
        SELECT state_json, version
        FROM state_snapshot
        WHERE user_id = ? AND state_type = ? AND state_key = ?
        """,
        (mutation.user_id, mutation.state_type, mutation.state_key),
    ).fetchone()
    current_version = int(row[1]) if row is not None else 0
    if current_version != mutation.expected_version:
        raise StateConflictError(
            f"状态版本冲突：{mutation.state_type}/{mutation.state_key} "
            f"期望 {mutation.expected_version}，实际 {current_version}"
        )
    if mutation.value is None:
        if row is None:
            raise StateConflictError("不能删除不存在的状态")
        connection.execute(
            "DELETE FROM state_snapshot WHERE user_id = ? AND state_type = ? AND state_key = ?",
            (mutation.user_id, mutation.state_type, mutation.state_key),
        )
        return StateChange(
            mutation.user_id,
            mutation.state_type,
            mutation.state_key,
            "delete",
            current_version,
            None,
        )

    encoded = _encode(mutation.value)
    next_version = current_version + 1
    if row is None:
        connection.execute(
            """
            INSERT INTO state_snapshot (
                user_id, state_type, state_key, state_json, version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                mutation.user_id,
                mutation.state_type,
                mutation.state_key,
                encoded,
                next_version,
                committed_at,
            ),
        )
        operation = "insert"
    else:
        connection.execute(
            """
            UPDATE state_snapshot
            SET state_json = ?, version = ?, updated_at = ?
            WHERE user_id = ? AND state_type = ? AND state_key = ?
            """,
            (
                encoded,
                next_version,
                committed_at,
                mutation.user_id,
                mutation.state_type,
                mutation.state_key,
            ),
        )
        operation = "update"
    return StateChange(
        mutation.user_id,
        mutation.state_type,
        mutation.state_key,
        operation,
        current_version or None,
        next_version,
    )


def _apply_location_mutation(
    connection: sqlite3.Connection,
    mutation: LocationMutation,
    committed_at: str,
) -> StateChange:
    row = connection.execute(
        "SELECT version FROM player_location WHERE user_id = ?",
        (mutation.user_id,),
    ).fetchone()
    current_version = int(row[0]) if row is not None else 0
    if current_version != mutation.expected_version:
        raise StateConflictError(
            f"位置版本冲突：期望 {mutation.expected_version}，实际 {current_version}"
        )
    if mutation.xy is None:
        if row is None:
            raise StateConflictError("不能删除不存在的位置")
        connection.execute(
            "DELETE FROM player_location WHERE user_id = ?",
            (mutation.user_id,),
        )
        return StateChange(
            mutation.user_id,
            "location",
            "main",
            "delete",
            current_version,
            None,
        )

    x, y = _validate_xy(mutation.xy)
    next_version = current_version + 1
    if row is None:
        connection.execute(
            """
            INSERT INTO player_location (user_id, x, y, version, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (mutation.user_id, x, y, next_version, committed_at),
        )
        operation = "insert"
    else:
        connection.execute(
            """
            UPDATE player_location
            SET x = ?, y = ?, version = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (x, y, next_version, committed_at, mutation.user_id),
        )
        operation = "update"
    return StateChange(
        mutation.user_id,
        "location",
        "main",
        operation,
        current_version or None,
        next_version,
    )


def _snapshot(
    address: StateAddress, row: sqlite3.Row | tuple[object, ...]
) -> StateSnapshot:
    state_json, version, updated_at = row
    value = json.loads(str(state_json))
    if not isinstance(value, dict):
        raise DatabaseError("状态 JSON 根值必须是对象")
    return StateSnapshot(address, _freeze_json(value), int(version), str(updated_at))


def _receipt_from_row(
    command: TransactionCommand,
    row: sqlite3.Row,
    *,
    replayed: bool,
) -> TransactionReceipt:
    stored = json.loads(str(row[2]))
    changes = tuple(
        StateChange(
            str(change["user_id"]),
            str(change["state_type"]),
            str(change["state_key"]),
            str(change["operation"]),
            _optional_int(change.get("before_version")),
            _optional_int(change.get("after_version")),
        )
        for change in stored.get("changes", [])
    )
    return TransactionReceipt(
        transaction_id=str(row[0]),
        user_id=command.user_id,
        request_id=command.request_id,
        business_type=str(row[1]),
        committed_at=str(row[3]),
        replayed=replayed,
        changes=changes,
    )


def _validate_command(command: TransactionCommand) -> None:
    for value, label in (
        (command.user_id, "user_id"),
        (command.request_id, "request_id"),
        (command.business_type, "business_type"),
    ):
        _validate_text(value, label)
    if not command.operations:
        raise ValueError("事务至少需要一项状态变更")
    addresses = set()
    for operation in command.operations:
        _validate_text(operation.user_id, "operation.user_id")
        if (
            isinstance(operation.expected_version, bool)
            or operation.expected_version < 0
        ):
            raise ValueError("expected_version 不能小于 0")
        if isinstance(operation, StateMutation):
            _validate_text(operation.state_type, "state_type")
            _validate_text(operation.state_key, "state_key")
            address = (operation.user_id, operation.state_type, operation.state_key)
        else:
            address = (operation.user_id, "location", "main")
        if address in addresses:
            raise ValueError("同一事务不能重复修改同一状态")
        addresses.add(address)
        if isinstance(operation, StateMutation) and operation.value is not None:
            if not isinstance(operation.value, Mapping):
                raise TypeError("状态 JSON 根值必须是对象")
            _encode(operation.value)
        if isinstance(operation, LocationMutation) and operation.xy is not None:
            _validate_xy(operation.xy)
    if not isinstance(command.payload, Mapping):
        raise TypeError("事务 payload 根值必须是对象")
    _encode(command.payload)


def _validate_address(address: StateAddress) -> None:
    _validate_text(address.user_id, "user_id")
    _validate_text(address.state_type, "state_type")
    _validate_text(address.state_key, "state_key")


def _validate_text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} 必须是无首尾空白的非空字符串")


def _command_json(command: TransactionCommand) -> dict[str, object]:
    return {
        "business_type": command.business_type,
        "operations": [_operation_json(operation) for operation in command.operations],
        "payload": _json_value(command.payload),
    }


def _change_json(change: StateChange) -> dict[str, object]:
    return {
        "user_id": change.user_id,
        "state_type": change.state_type,
        "state_key": change.state_key,
        "operation": change.operation,
        "before_version": change.before_version,
        "after_version": change.after_version,
    }


def _operation_json(operation: StateMutation | LocationMutation) -> dict[str, object]:
    if isinstance(operation, StateMutation):
        return {
            "kind": "state",
            "user_id": operation.user_id,
            "state_type": operation.state_type,
            "state_key": operation.state_key,
            "value": _json_value(operation.value),
            "expected_version": operation.expected_version,
        }
    return {
        "kind": "location",
        "user_id": operation.user_id,
        "xy": list(operation.xy) if operation.xy is not None else None,
        "expected_version": operation.expected_version,
    }


def _validate_xy(value: object) -> tuple[int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise ValueError("xy 必须是两个整数")
    return int(value[0]), int(value[1])


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(raw) for key, raw in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze_json(raw) for key, raw in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _encode(value: object) -> str:
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("状态数据必须是可序列化 JSON") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _chunks[T](values: tuple[T, ...], size: int) -> Iterator[tuple[T, ...]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


__all__ = ["SQLiteStateStore"]
