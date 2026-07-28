"""组件共用的最小 SQLite 连接和事务边界。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


def record_exists(
    connection: sqlite3.Connection,
    table: str,
    user_id: str,
) -> bool:
    """查询指定表是否存在该用户记录；表名只接受 ASCII 标识符。"""

    normalized_table = str(table or "").strip()
    if not normalized_table.isascii() or not normalized_table.isidentifier():
        raise ValueError(f"SQLite 表名不合法：{table}")
    return connection.execute(
        f"SELECT 1 FROM {normalized_table} WHERE user_id = ?",
        (user_id,),
    ).fetchone() is not None


class Database:
    """只提供连接和事务，不定义任何玩法状态。"""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path).expanduser().resolve()
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def initialize(self, schema: str) -> None:
        """执行一个组件提供的建表 SQL，并立即释放连接。"""

        connection = self.connect()
        try:
            connection.executescript(str(schema or ""))
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN DEFERRED")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


__all__ = ["Database", "record_exists"]
