"""正式资源池抽取公共微服务。"""

from __future__ import annotations

import random
import secrets
from threading import RLock

from game.core.data import JsonDataService

from .contracts import (
    ALLOW_REPEATS,
    EXPAND_DEDUPLICATED,
    POOL_MODES,
    PoolEntry,
    PoolRequest,
    PoolResult,
    PoolStatus,
)
from .selection import inverse_weighted_sample

WEIGHTED_SECTIONS = frozenset({"敌人", "物品", "功法", "附魔", "宝石"})


class PoolService:
    """从 JSON 数据微服务展开候选，并执行统一逆权重抽取。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._initialized = False
        self._candidate_lock = RLock()
        self._candidate_cache: dict[
            tuple[tuple[str, ...], str, bool],
            tuple[PoolEntry, ...],
        ] = {}
        self._weights: dict[str, dict[str, int]] = {}

    def initialize(self) -> PoolStatus:
        if self._initialized:
            raise RuntimeError("资源池微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于资源池微服务启动")
        for section in sorted(WEIGHTED_SECTIONS):
            self._weights[section] = {
                identity: _weight(identity, fields.get("权重"))
                for identity, fields in self._data.entity_fields(section, ("权重",))
            }
        self._initialized = True
        return self.status()

    def status(self) -> PoolStatus:
        return PoolStatus(
            initialized=self._initialized,
            modes=(ALLOW_REPEATS, EXPAND_DEDUPLICATED),
        )

    def draw(self, request: PoolRequest) -> PoolResult:
        if not self._initialized:
            raise RuntimeError("资源池微服务尚未初始化")
        selected_mode = str(request.mode or "").strip()
        if selected_mode not in POOL_MODES:
            raise ValueError(
                f"未知资源池抽取模式：{selected_mode or '<空>'}"
            )
        source_files = tuple(str(value).strip() for value in request.file_ids)
        if not source_files or any(not value for value in source_files):
            raise ValueError("资源池文件名不能为空")
        section_name = str(request.section or "").strip()
        if section_name not in WEIGHTED_SECTIONS:
            raise ValueError(
                f"该集合不使用权重抽取：{section_name or '<空>'}"
            )
        deduplicated = selected_mode == EXPAND_DEDUPLICATED
        candidates = self._candidates(source_files, section_name, deduplicated)
        seed_value = _seed(request.seed)
        entries = inverse_weighted_sample(
            random.Random(seed_value),
            candidates,
            tuple(entry.weight for entry in candidates),
            count=request.count,
            replace=not deduplicated,
        )
        return PoolResult(
            mode=selected_mode,
            seed=seed_value,
            section=section_name,
            source_files=source_files,
            candidate_count=len(candidates),
            entries=tuple(entries),
        )

    def _candidates(
        self,
        source_files: tuple[str, ...],
        section: str,
        deduplicated: bool,
    ) -> tuple[PoolEntry, ...]:
        cache_key = (source_files, section, deduplicated)
        with self._candidate_lock:
            cached = self._candidate_cache.get(cache_key)
            if cached is not None:
                return cached
            identities = self._data.pool_members(
                source_files,
                section,
                deduplicate=deduplicated,
            )
            candidates = tuple(
                PoolEntry(identity=identity, weight=self._weights[section][identity])
                for identity in identities
            )
            self._candidate_cache[cache_key] = candidates
            return candidates


def _weight(identity: str, weight: object) -> int:
    if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
        raise ValueError(f"资源池实体 {identity} 缺少正整数权重")
    return weight


def _seed(value: int | None) -> int:
    if value is None:
        return secrets.randbits(64)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("随机种子必须是整数")
    return value


__all__ = [
    "PoolService",
]
