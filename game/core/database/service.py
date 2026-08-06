"""异步核心数据库微服务门面。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .contracts import (
    DatabaseStatus,
    StateAddress,
    StateSnapshot,
    TransactionCommand,
    TransactionReceipt,
)
from .storage import SQLiteStateStore


class DatabaseService:
    """为所有玩法提供异步状态读取和原子事务提交。"""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5000) -> None:
        self._store = SQLiteStateStore(path, busy_timeout_ms=busy_timeout_ms)
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._store.path

    def initialize(self) -> DatabaseStatus:
        """启动时建表；服务运行期间不做结构迁移。"""

        if self._initialized:
            raise RuntimeError("核心数据库已经初始化")
        self._store.initialize()
        self._initialized = True
        return self.status()

    def status(self) -> DatabaseStatus:
        state_count, transaction_count = (
            self._store.counts() if self._initialized else (0, 0)
        )
        return DatabaseStatus(
            initialized=self._initialized,
            path=self.path,
            state_count=state_count,
            transaction_count=transaction_count,
        )

    async def get(self, address: StateAddress) -> StateSnapshot | None:
        self._require_initialized()
        return await asyncio.to_thread(self._store.get, address)

    async def list_for_user(
        self, user_id: str, *, state_type: str | None = None
    ) -> tuple[StateSnapshot, ...]:
        self._require_initialized()
        return await asyncio.to_thread(self._store.list_for_user, user_id, state_type)

    async def commit(self, command: TransactionCommand) -> TransactionReceipt:
        self._require_initialized()
        return await asyncio.to_thread(self._store.commit, command)

    def close(self) -> None:
        self._initialized = False

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("核心数据库尚未初始化")


__all__ = ["DatabaseService"]
