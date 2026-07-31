"""正式资源池抽取公共微服务。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import random
import secrets
from collections.abc import Sequence

from game.core.data import JsonDataService

from .models import PoolEntry, PoolResult
from .selection import inverse_weighted_sample


ALLOW_REPEATS = "允许重复"
EXPAND_DEDUPLICATED = "展开去重"
POOL_MODES = frozenset({ALLOW_REPEATS, EXPAND_DEDUPLICATED})


@dataclass(frozen=True)
class PoolStatus:
    initialized: bool
    modes: tuple[str, ...]


class PoolService:
    """从 JSON 数据微服务展开候选，并执行统一逆权重抽取。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._initialized = False

    def initialize(self) -> PoolStatus:
        if self._initialized:
            raise RuntimeError("资源池微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于资源池微服务启动")
        self._initialized = True
        return self.status()

    def status(self) -> PoolStatus:
        return PoolStatus(
            initialized=self._initialized,
            modes=(ALLOW_REPEATS, EXPAND_DEDUPLICATED),
        )

    def draw(
        self,
        *,
        file_ids: Sequence[str],
        section: str,
        count: int,
        mode: str,
        seed: int | None = None,
    ) -> PoolResult:
        if not self._initialized:
            raise RuntimeError("资源池微服务尚未初始化")
        selected_mode = str(mode or "").strip()
        if selected_mode not in POOL_MODES:
            raise ValueError(
                f"未知资源池抽取模式：{selected_mode or '<空>'}"
            )
        source_files = tuple(str(value).strip() for value in file_ids)
        if not source_files or any(not value for value in source_files):
            raise ValueError("资源池文件名不能为空")
        section_name = str(section or "").strip()
        deduplicated = selected_mode == EXPAND_DEDUPLICATED
        expanded = self._data.expand_pool(
            source_files,
            section_name,
            deduplicate=deduplicated,
        )
        candidates = tuple(
            _pool_entry(identity, definition)
            for identity, definition in expanded
        )
        seed_value = _seed(seed)
        entries = inverse_weighted_sample(
            random.Random(seed_value),
            candidates,
            tuple(entry.weight for entry in candidates),
            count=count,
            replace=not deduplicated,
        )
        return PoolResult(
            mode=selected_mode,
            seed=seed_value,
            section=section_name,
            source_files=source_files,
            candidate_count=len(candidates),
            entries=tuple(
                PoolEntry(
                    identity=entry.identity,
                    weight=entry.weight,
                    definition=deepcopy(dict(entry.definition)),
                )
                for entry in entries
            ),
        )


def _pool_entry(identity: str, definition: dict) -> PoolEntry:
    weight = definition.get("权重")
    if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
        raise ValueError(f"资源池实体 {identity} 缺少正整数权重")
    return PoolEntry(
        identity=str(identity),
        weight=weight,
        definition=deepcopy(definition),
    )


def _seed(value: int | None) -> int:
    if value is None:
        return secrets.randbits(64)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("随机种子必须是整数")
    return value


__all__ = [
    "ALLOW_REPEATS",
    "EXPAND_DEDUPLICATED",
    "POOL_MODES",
    "PoolService",
    "PoolStatus",
]
