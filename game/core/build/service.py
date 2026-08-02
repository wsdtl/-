"""按正式资源池与相冲 JSON 生成合法构筑。"""

from __future__ import annotations

import random
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

from game.core.data import JsonDataService
from game.core.pool import EXPAND_DEDUPLICATED, PoolRequest, PoolService

from .contracts import (
    BuildError,
    BuildRequest,
    BuildResult,
    BuildSelection,
    BuildSlotRequest,
    BuildStatus,
)

BUILD_SECTIONS = frozenset({"功法", "附魔", "宝石"})


class BuildService:
    """只负责候选展开、逆权重抽取和相冲裁决。"""

    def __init__(self, data: JsonDataService, pools: PoolService) -> None:
        self._data = data
        self._pools = pools
        self._attempt_limit = 0
        self._conflicts: tuple[frozenset[str], ...] = ()
        self._mechanisms_by_entity: dict[tuple[str, str], frozenset[str]] = {}

    def initialize(self) -> BuildStatus:
        if self._attempt_limit:
            raise RuntimeError("构筑微服务已经初始化")
        if not self._pools.status().initialized:
            raise RuntimeError("资源池微服务必须先于构筑微服务启动")
        rules = self._data.dataset("构筑规则")
        generation = _mapping(rules.get("生成"), "构筑生成规则")
        _strict_fields(
            generation,
            {"相冲规则", "尝试上限", "权重算法", "候选去重"},
            "构筑生成规则",
        )
        if _text(generation.get("权重算法"), "构筑权重算法") != "倒数":
            raise BuildError("构筑微服务只接受资源池的倒数权重算法")
        if _text(generation.get("候选去重"), "构筑候选去重") != "编号":
            raise BuildError("构筑候选必须按编号去重")
        self._attempt_limit = _positive_int(
            generation.get("尝试上限"), "构筑尝试上限"
        )
        conflict_name = _text(generation.get("相冲规则"), "相冲规则")
        rows = _sequence(rules.get(conflict_name), f"相冲规则 {conflict_name}")
        self._conflicts = self._load_conflicts(rows)
        self._mechanisms_by_entity = self._index_entity_mechanisms()
        return self.status()

    def status(self) -> BuildStatus:
        return BuildStatus(
            initialized=bool(self._attempt_limit),
            conflict_count=len(self._conflicts),
            attempt_limit=self._attempt_limit,
        )

    def generate(self, request: BuildRequest) -> BuildResult:
        self._require_initialized()
        slots = self._validate_slots(request.slots)
        seed = _seed(request.seed)
        rng = random.Random(seed)
        for attempt in range(1, self._attempt_limit + 1):
            selections = tuple(
                self._draw_slot(slot, rng.getrandbits(64)) for slot in slots
            )
            if not self._has_conflict(selections):
                return BuildResult(
                    seed=seed,
                    attempts=attempt,
                    selections=selections,
                )
        raise BuildError(f"在 {self._attempt_limit} 次尝试内没有生成合法构筑")

    def _load_conflicts(
        self,
        rows: Sequence[Any],
    ) -> tuple[frozenset[str], ...]:
        mechanisms = set(self._data.entities("机制"))
        names: set[str] = set()
        conflicts: list[frozenset[str]] = []
        for raw in rows:
            row = _mapping(raw, "相冲规则")
            _strict_fields(row, {"名称", "机制"}, "相冲规则")
            name = _text(row.get("名称"), "相冲规则名称")
            values = frozenset(_strings(row.get("机制"), f"相冲规则 {name} 机制"))
            if name in names:
                raise BuildError(f"相冲规则名称重复：{name}")
            if len(values) < 2:
                raise BuildError(f"相冲规则至少需要两个机制：{name}")
            unknown = values - mechanisms
            if unknown:
                raise BuildError(
                    f"相冲规则 {name} 引用未知机制：{'、'.join(sorted(unknown))}"
                )
            names.add(name)
            conflicts.append(values)
        return tuple(conflicts)

    def _index_entity_mechanisms(
        self,
    ) -> dict[tuple[str, str], frozenset[str]]:
        result: dict[tuple[str, str], frozenset[str]] = {}
        mechanisms = set(self._data.entities("机制"))
        for section in sorted(BUILD_SECTIONS):
            for identity, raw in self._data.entities(section).items():
                _strict_fields(raw, {"编号", "名称", "权重", "能力"}, f"{section} {identity}")
                if str(raw.get("编号")) != identity:
                    raise BuildError(f"{section} {identity} 编号与索引不一致")
                references = frozenset(_mechanism_references(raw.get("能力")))
                unknown = references - mechanisms
                if unknown:
                    raise BuildError(
                        f"{section} {identity} 引用未知机制：{'、'.join(sorted(unknown))}"
                    )
                result[(section, identity)] = references
        return result

    @staticmethod
    def _validate_slots(
        slots: tuple[BuildSlotRequest, ...],
    ) -> tuple[BuildSlotRequest, ...]:
        if not slots:
            raise BuildError("构筑请求不能为空")
        sections: set[str] = set()
        for slot in slots:
            if slot.section not in BUILD_SECTIONS:
                raise BuildError(f"未知构筑类别：{slot.section}")
            if slot.section in sections:
                raise BuildError(f"构筑类别重复：{slot.section}")
            if isinstance(slot.count, bool) or not isinstance(slot.count, int) or slot.count < 0:
                raise BuildError(f"{slot.section}构筑数量必须是非负整数")
            if slot.full_pool == bool(slot.file_ids):
                raise BuildError(f"{slot.section}必须且只能选择全池或指定池")
            sections.add(slot.section)
        return slots

    def _draw_slot(self, slot: BuildSlotRequest, seed: int) -> BuildSelection:
        if slot.count == 0:
            return BuildSelection(section=slot.section, identities=())
        try:
            result = self._pools.draw(
                PoolRequest(
                    section=slot.section,
                    count=slot.count,
                    mode=EXPAND_DEDUPLICATED,
                    file_ids=slot.file_ids,
                    full_pool=slot.full_pool,
                    seed=seed,
                )
            )
        except (TypeError, ValueError) as exc:
            raise BuildError(f"{slot.section}候选池不能形成构筑：{exc}") from exc
        return BuildSelection(section=slot.section, identities=result.identities)

    def _has_conflict(self, selections: tuple[BuildSelection, ...]) -> bool:
        mechanisms = set()
        for selection in selections:
            for identity in selection.identities:
                mechanisms.update(self._mechanisms_by_entity[(selection.section, identity)])
        return any(conflict <= mechanisms for conflict in self._conflicts)

    def _require_initialized(self) -> None:
        if not self._attempt_limit:
            raise RuntimeError("构筑微服务尚未初始化")


def _mechanism_references(value: Any) -> tuple[str, ...]:
    result: list[str] = []

    def visit(current: Any) -> None:
        if isinstance(current, Mapping):
            mechanism = current.get("机制")
            if isinstance(mechanism, str):
                result.append(mechanism)
            for child in current.values():
                visit(child)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            for child in current:
                visit(child)

    visit(value)
    return tuple(result)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BuildError(f"{label}必须是对象")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise BuildError(f"{label}必须是列表")
    return value


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise BuildError(f"{label}不能为空")
    return result


def _strings(value: Any, label: str) -> tuple[str, ...]:
    result = tuple(_text(item, label) for item in _sequence(value, label))
    if len(result) != len(set(result)):
        raise BuildError(f"{label}不能重复")
    return result


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BuildError(f"{label}必须是正整数")
    return value


def _seed(value: int | None) -> int:
    if value is None:
        return secrets.randbits(64)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BuildError("构筑随机种子必须是整数")
    return value


def _strict_fields(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    missing = allowed - set(value)
    if unknown or missing:
        details = []
        if unknown:
            details.append("未知字段 " + "、".join(sorted(unknown)))
        if missing:
            details.append("缺少字段 " + "、".join(sorted(missing)))
        raise BuildError(f"{label}字段不完整：{'；'.join(details)}")


__all__ = ["BuildService"]
