"""只解释正式 JSON 的共用成长计算服务。"""

from __future__ import annotations

import math
import random
import secrets
from collections.abc import Mapping, Sequence

from game.core.data import JsonDataError, JsonDataService
from game.core.pool import EXPAND_DEDUPLICATED, PoolRequest, PoolService

from .contracts import (
    ExperienceAdvance,
    GrowthError,
    GrowthStatus,
    RandomCultivationBuild,
    RealmDefinition,
    WeaponAdvance,
)

_CATEGORIES = ("功法", "真意", "气机")


class GrowthService:
    """为人物和道侣提供同一套等级、境界、武器与构筑计算。"""

    def __init__(self, data: JsonDataService, pool: PoolService) -> None:
        self._data = data
        self._pool = pool
        self._initialized = False
        self._cultivator_rule: Mapping[str, object] = {}
        self._weapon_rule: Mapping[str, object] = {}
        self._weapon_stages: tuple[Mapping[str, object], ...] = ()
        self._realms: dict[str, RealmDefinition] = {}
        self._conflicts: tuple[frozenset[str], ...] = ()
        self._attempt_limit = 0

    def initialize(self) -> GrowthStatus:
        if self._initialized:
            raise RuntimeError("成长核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于成长核心启动")
        if not self._pool.status().initialized:
            raise RuntimeError("资源池微服务必须先于成长核心启动")
        rules = self._data.dataset("角色规则")
        self._cultivator_rule = _mapping(rules.get("修士修炼"), "修士修炼.json")
        forging = self._data.dataset("炼器规则")
        self._weapon_rule = _mapping(forging.get("本命武器"), "本命武器.json")
        weapon_stage_rule = _mapping(forging.get("器则"), "器则.json")
        self._weapon_stages = tuple(
            _mapping(value, "器则.器阶[]")
            for value in _sequence(weapon_stage_rule.get("器阶"), "器则.器阶")
        )
        self._realms = {
            realm_id: RealmDefinition(
                realm_id,
                _text(value.get("名称"), f"境界 {realm_id}.名称"),
                _positive_int(value.get("等级下限"), f"境界 {realm_id}.等级下限"),
                _positive_int(value.get("等级上限"), f"境界 {realm_id}.等级上限"),
                str(value.get("下一境界") or "").strip(),
            )
            for realm_id, value in self._data.entities("境界").items()
        }
        build_rules = self._data.dataset("构筑规则")
        generation = _mapping(build_rules.get("生成"), "构筑/生成.json")
        self._attempt_limit = _positive_int(
            generation.get("尝试上限"), "构筑.尝试上限"
        )
        self._conflicts = tuple(
            frozenset(_strings(_mapping(row, "构筑/相冲.json[]").get("机制"), "相冲.机制"))
            for row in _sequence(build_rules.get("相冲"), "构筑/相冲.json")
        )
        self._validate_static_rules()
        self._initialized = True
        return self.status()

    def status(self) -> GrowthStatus:
        return GrowthStatus(
            self._initialized,
            len(self._realms),
            int(self._cultivator_rule.get("等级上限") or 0),
            int(self._weapon_rule.get("等级上限") or 0),
        )

    def realm(self, realm_id: str) -> RealmDefinition:
        self._require_initialized()
        value = self._realms.get(str(realm_id or "").strip())
        if value is None:
            raise GrowthError(f"未知境界：{realm_id or '<空>'}")
        return value

    def next_realm(self, realm_id: str) -> RealmDefinition:
        current = self.realm(realm_id)
        if not current.next_realm_id:
            raise GrowthError(f"{current.name}已经是最高境界")
        return self.realm(current.next_realm_id)

    def experience_required(self, level: int, *, weapon: bool = False) -> int:
        self._require_initialized()
        rule = self._weapon_rule if weapon else self._cultivator_rule
        maximum = _positive_int(rule.get("等级上限"), "成长.等级上限")
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= maximum:
            raise GrowthError(f"等级必须在1至{maximum}之间")
        if level >= maximum:
            return 0
        curve = _mapping(rule.get("经验"), "成长.经验")
        base = math.floor(
            _number(curve.get("幂次基数"), "经验.幂次基数")
            * level ** _number(curve.get("等级幂次"), "经验.等级幂次")
            + _number(curve.get("等级基数"), "经验.等级基数") * level
        )
        late = _mapping(curve.get("后段"), "经验.后段")
        start = _positive_int(late.get("起始等级"), "经验.后段.起始等级")
        if level <= start:
            return max(1, base)
        span = _positive_int(late.get("跨度"), "经验.后段.跨度")
        progress = max(0.0, (level - start) / span)
        multiplier = 1.0
        for prefix in ("中段", "高段", "终段"):
            multiplier += _number(late.get(f"{prefix}系数"), f"经验.后段.{prefix}系数") * (
                progress
                ** _number(late.get(f"{prefix}幂次"), f"经验.后段.{prefix}幂次")
            )
        return max(1, math.floor(base * multiplier))

    def advance_cultivator(
        self,
        *,
        level: int,
        experience: int,
        realm_id: str,
        gained: int,
    ) -> ExperienceAdvance:
        self._require_initialized()
        current_realm = self.realm(realm_id)
        return self._advance(
            level=level,
            experience=experience,
            gained=gained,
            maximum_level=current_realm.maximum_level,
            weapon=False,
        )

    def advance_weapon(
        self, *, level: int, experience: int, gained: int
    ) -> WeaponAdvance:
        self._require_initialized()
        before_stage, before_slots = self.weapon_stage(level)
        result = self._advance(
            level=level,
            experience=experience,
            gained=gained,
            maximum_level=_positive_int(self._weapon_rule.get("等级上限"), "武器等级上限"),
            weapon=True,
        )
        after_stage, after_slots = self.weapon_stage(result.level_after)
        return WeaponAdvance(
            result.level_before,
            result.level_after,
            result.experience_before,
            result.experience_after,
            result.experience_gained,
            before_stage,
            after_stage,
            before_slots,
            after_slots,
        )

    def weapon_stage(self, level: int) -> tuple[str, int]:
        self._require_initialized()
        for stage in self._weapon_stages:
            bounds = _integer_pair(stage.get("等级范围"), "器阶.等级范围")
            if bounds[0] <= level <= bounds[1]:
                return (
                    _text(stage.get("名称"), "器阶.名称"),
                    _nonnegative_int(stage.get("开放器律孔"), "器阶.开放器律孔"),
                )
        raise GrowthError(f"本命武器等级没有对应器阶：{level}")

    def cultivator_attribute_growth(
        self, levels: int, *, multiplier: float = 1.0
    ) -> Mapping[str, int | float]:
        """计算若干次升级带来的属性增量。"""

        self._require_initialized()
        if isinstance(levels, bool) or not isinstance(levels, int) or levels < 0:
            raise GrowthError("升级次数必须是非负整数")
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or multiplier <= 0:
            raise GrowthError("成长倍率必须大于0")
        growth = _mapping(
            _mapping(self._cultivator_rule.get("属性成长"), "修士修炼.属性成长").get("每级"),
            "修士修炼.属性成长.每级",
        )
        result: dict[str, int | float] = {}
        for attribute, raw in growth.items():
            value = _number(raw, f"每级成长.{attribute}") * levels * multiplier
            result[str(attribute)] = int(value) if value.is_integer() else round(value, 4)
        return result

    def law_allowed(self, weapon_level: int, law_stage: str) -> bool:
        """低阶器律可以保留或覆入更高阶本命武器。"""

        current_name, _ = self.weapon_stage(weapon_level)
        order = {
            _text(stage.get("名称"), "器阶.名称"): index
            for index, stage in enumerate(self._weapon_stages)
        }
        normalized = str(law_stage or "").strip()
        if normalized not in order:
            raise GrowthError(f"未知器律器阶：{normalized or '<空>'}")
        return order[normalized] <= order[current_name]

    def random_companion_build(
        self,
        *,
        pools: Mapping[str, str],
        slots: Mapping[str, int],
        seed: int | None = None,
    ) -> RandomCultivationBuild:
        self._require_initialized()
        actual_seed = secrets.randbits(64) if seed is None else seed
        if isinstance(actual_seed, bool) or not isinstance(actual_seed, int):
            raise GrowthError("随机种子必须是整数")
        source = random.Random(actual_seed)
        for _ in range(self._attempt_limit):
            selected: dict[str, tuple[str, ...]] = {}
            for category in _CATEGORIES:
                count = _positive_int(slots.get(category), f"道侣.{category}槽位")
                pool_name = _text(pools.get(category), f"道侣.{category}池")
                selected[category] = self._pool.draw(
                    PoolRequest(
                        section=category,
                        count=count,
                        mode=EXPAND_DEDUPLICATED,
                        file_ids=(pool_name,),
                        seed=source.getrandbits(64),
                    )
                ).entity_ids
            if self.build_conflict(selected) is None:
                return RandomCultivationBuild(
                    actual_seed,
                    selected["功法"],
                    selected["真意"],
                    selected["气机"],
                )
        raise GrowthError("道侣个人修行池无法生成无相冲构筑")

    def build_conflict(
        self, build: Mapping[str, Sequence[str]]
    ) -> frozenset[str] | None:
        self._require_initialized()
        mechanism_ids: set[str] = set()
        for category in _CATEGORIES:
            for content_id in build.get(category, ()):
                mechanism_ids.update(self._mechanism_ids(category, content_id))
        return next(
            (conflict for conflict in self._conflicts if conflict <= mechanism_ids),
            None,
        )

    def _advance(
        self,
        *,
        level: int,
        experience: int,
        gained: int,
        maximum_level: int,
        weapon: bool,
    ) -> ExperienceAdvance:
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (level, experience, gained)):
            raise GrowthError("等级和经验必须是整数")
        if level < 1 or experience < 0 or gained < 0:
            raise GrowthError("等级必须为正，经验不能为负")
        current_level = level
        current_experience = experience + gained
        while current_level < maximum_level:
            required = self.experience_required(current_level, weapon=weapon)
            if current_experience < required:
                break
            current_experience -= required
            current_level += 1
        return ExperienceAdvance(
            level,
            current_level,
            experience,
            current_experience,
            gained,
            current_level - level,
            current_level >= maximum_level,
        )

    def _mechanism_ids(self, section: str, content_id: str) -> set[str]:
        value = self._data.entity(section, str(content_id))
        result: set[str] = set()
        pending: list[object] = [value]
        while pending:
            current = pending.pop()
            if isinstance(current, Mapping):
                pending.extend(current.values())
            elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
                pending.extend(current)
            elif isinstance(current, str) and len(current) == 6 and current.isdecimal():
                try:
                    record = self._data.entity_record("机制", current)
                except JsonDataError:
                    continue
                if record.entity_id == current:
                    result.add(current)
        return result

    def _validate_static_rules(self) -> None:
        maximum = _positive_int(self._cultivator_rule.get("等级上限"), "修士等级上限")
        weapon_maximum = _positive_int(self._weapon_rule.get("等级上限"), "武器等级上限")
        if maximum != 100 or weapon_maximum != 100:
            raise JsonDataError("当前成长契约要求人物和本命武器等级上限均为100")
        if not self._realms:
            raise JsonDataError("境界定义不能为空")
        for realm in self._realms.values():
            if realm.next_realm_id and realm.next_realm_id not in self._realms:
                raise JsonDataError(f"境界下一境界不存在：{realm.realm_id}")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("成长核心微服务尚未初始化")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是数组")
    return tuple(value)


def _strings(value: object, label: str) -> tuple[str, ...]:
    result = tuple(_text(raw, label) for raw in _sequence(value, label))
    if not result:
        raise JsonDataError(f"{label}不能为空")
    return result


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JsonDataError(f"{label}必须是非空文本")
    return value.strip()


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JsonDataError(f"{label}必须是数值")
    return float(value)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JsonDataError(f"{label}必须是非负整数")
    return value


def _integer_pair(value: object, label: str) -> tuple[int, int]:
    values = _sequence(value, label)
    if len(values) != 2 or any(isinstance(raw, bool) or not isinstance(raw, int) for raw in values):
        raise JsonDataError(f"{label}必须是两个整数")
    return int(values[0]), int(values[1])


__all__ = ["GrowthService"]
