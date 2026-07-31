"""资源池微服务的公开结果模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PoolEntry:
    """一次抽取命中的实体及其抽取权重。"""

    identity: str
    weight: int
    definition: Mapping[str, Any]


@dataclass(frozen=True)
class PoolResult:
    """可通过 seed 完整复现的一次资源池抽取。"""

    mode: str
    seed: int
    section: str
    source_files: tuple[str, ...]
    candidate_count: int
    entries: tuple[PoolEntry, ...]

    @property
    def identities(self) -> tuple[str, ...]:
        return tuple(entry.identity for entry in self.entries)


__all__ = ["PoolEntry", "PoolResult"]
