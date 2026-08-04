"""把世界位置或秘境场景解析为战斗核心可执行的战场引用。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from game.core.combat import CombatFieldSpec
from game.core.data import JsonDataService
from game.core.world import LocationReference, WorldService

from .contracts import (
    BattlefieldEnvironment,
    BattlefieldError,
    BattlefieldStatus,
)


class BattlefieldService:
    """拥有环境选择边界，不保存人物位置，也不执行战斗。"""

    def __init__(self, data: JsonDataService, world: WorldService) -> None:
        self._data = data
        self._world = world
        self._environments: dict[str, BattlefieldEnvironment] = {}
        self._environment_by_name: dict[str, BattlefieldEnvironment] = {}
        self._surface_terrain_count = 0
        self._default_realm_environment = ""

    def initialize(self) -> BattlefieldStatus:
        if self._environments:
            raise RuntimeError("战场环境微服务已经初始化")
        if not self._world.status().initialized:
            raise RuntimeError("世界微服务必须先于战场环境微服务启动")
        rules = self._data.dataset("战斗规则")
        raw_rules = _mapping(rules.get("环境"), "环境规则")
        default_environment = _text(
            raw_rules.get("秘境默认环境"), "秘境默认环境"
        )
        environments: dict[str, BattlefieldEnvironment] = {}
        by_name: dict[str, BattlefieldEnvironment] = {}
        for identity, raw_value in self._data.entities("战场环境").items():
            value = _mapping(raw_value, f"战场环境 {identity}")
            name = _text(value.get("名称"), f"战场环境 {identity} 名称")
            stages = tuple(
                _text(
                    _mapping(raw_stage, f"战场环境 {identity} 阶段").get("名称"),
                    f"战场环境 {identity} 阶段名称",
                )
                for raw_stage in _sequence(
                    value.get("阶段"), f"战场环境 {identity} 阶段"
                )
            )
            if not stages:
                raise BattlefieldError(f"战场环境 {identity} 没有阶段")
            environment = BattlefieldEnvironment(identity, name, stages)
            if name in by_name:
                raise BattlefieldError(f"战场环境名称重复：{name}")
            environments[identity] = environment
            by_name[name] = environment

        try:
            realm_environment = environments[default_environment]
            realm_raw = self._data.entity("战场环境", default_environment)
        except KeyError as exc:
            raise BattlefieldError("秘境默认环境不存在") from exc
        realm_stages = _sequence(realm_raw.get("阶段"), "秘境默认环境阶段")
        if len(realm_stages) != 1:
            raise BattlefieldError("秘境默认环境必须只有一个阶段")
        realm_stage = _mapping(realm_stages[0], "秘境默认环境阶段")
        if realm_stage.get("入阶能力") or realm_stage.get("常驻能力"):
            raise BattlefieldError("秘境默认环境必须完全没有战斗能力")

        terrain_names = {location.terrain for location in self._world.locations()}
        missing = terrain_names - set(by_name)
        if missing:
            raise BattlefieldError(
                "地点地形没有对应战场环境：" + "、".join(sorted(missing))
            )
        self._environments = environments
        self._environment_by_name = by_name
        self._surface_terrain_count = len(terrain_names)
        self._default_realm_environment = realm_environment.identity
        return self.status()

    def status(self) -> BattlefieldStatus:
        return BattlefieldStatus(
            initialized=bool(self._environments),
            environment_count=len(self._environments),
            surface_terrain_count=self._surface_terrain_count,
            default_realm_environment=self._default_realm_environment,
        )

    def environment(self, identity: str) -> BattlefieldEnvironment:
        self._require_initialized()
        key = _text(identity, "战场环境编号")
        try:
            return self._environments[key]
        except KeyError as exc:
            raise BattlefieldError(f"战场环境不存在：{key}") from exc

    def surface(self, reference: LocationReference) -> CombatFieldSpec:
        """登记地点或其精确 xy 是地表战斗坐标的唯一来源。"""

        self._require_initialized()
        location = self._world.location(reference)
        try:
            environment = self._environment_by_name[location.terrain]
        except KeyError as exc:
            raise BattlefieldError(
                f"地点地形没有对应战场环境：{location.terrain}"
            ) from exc
        return CombatFieldSpec(
            environment_id=environment.identity,
            scene=location.identity,
            origin="地表",
            coordinate=(location.coordinate.x, location.coordinate.y),
            altitude=location.altitude,
            terrain=location.terrain,
        )

    def realm(
        self,
        scene: str,
        *,
        environment_id: str | None = None,
    ) -> CombatFieldSpec:
        """秘境不伪造地表 xy，未指定环境时使用无相境。"""

        self._require_initialized()
        identity = environment_id or self._default_realm_environment
        environment = self.environment(identity)
        return CombatFieldSpec(
            environment_id=environment.identity,
            scene=_text(scene, "秘境场景"),
            origin="秘境",
        )

    def _require_initialized(self) -> None:
        if not self._environments:
            raise RuntimeError("战场环境微服务尚未初始化")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BattlefieldError(f"{label}必须是字典")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise BattlefieldError(f"{label}必须是列表")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BattlefieldError(f"{label}必须是非空字符串")
    return value.strip()


__all__ = ["BattlefieldService"]
