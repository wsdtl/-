"""资源池微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

ALLOW_REPEATS = "允许重复"
EXPAND_DEDUPLICATED = "展开去重"
POOL_MODES = frozenset({ALLOW_REPEATS, EXPAND_DEDUPLICATED})


@dataclass(frozen=True)
class PoolStatus:
    initialized: bool
    modes: tuple[str, ...]


@dataclass(frozen=True)
class PoolRequest:
    file_ids: tuple[str, ...]
    section: str
    count: int
    mode: str
    seed: int | None = None


@dataclass(frozen=True)
class PoolEntry:
    identity: str
    weight: int


@dataclass(frozen=True)
class PoolResult:
    mode: str
    seed: int
    section: str
    source_files: tuple[str, ...]
    candidate_count: int
    entries: tuple[PoolEntry, ...]

    @property
    def identities(self) -> tuple[str, ...]:
        return tuple(entry.identity for entry in self.entries)


__all__ = [
    "ALLOW_REPEATS",
    "EXPAND_DEDUPLICATED",
    "POOL_MODES",
    "PoolEntry",
    "PoolRequest",
    "PoolResult",
    "PoolStatus",
]
