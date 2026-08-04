"""把世界位置或秘境场景解析为战斗核心可执行的战场引用。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from game.core.combat import CombatFieldSpec
from game.core.data import JsonDataService
from game.core.world import (
    LocationReference,
    SurfaceCoordinate,
    WorldDataError,
    WorldService,
)

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
        for identity, fields in self._data.entity_fields(
            "战场环境", ("名称",)
        ):
            name = _text(fields["名称"], f"战场环境 {identity} 名称")
            environment = BattlefieldEnvironment(identity, name)
            if name in by_name:
                raise BattlefieldError(f"战场环境名称重复：{name}")
            environments[identity] = environment
            by_name[name] = environment

        try:
            realm_environment = environments[default_environment]
        except KeyError as exc:
            raise BattlefieldError("秘境默认环境不存在") from exc

        terrain_names = {
            location.terrain for location in self._world.locations()
        }
        terrain_names.update(
            partition.terrain
            for region in self._world.regions()
            for partition in region.terrain_partitions
        )
        missing = terrain_names - set(by_name)
        if missing:
            raise BattlefieldError(
                "区域地形没有对应战场环境：" + "、".join(sorted(missing))
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
        """按地点名或任意精确 xy 解析地表战场。"""

        self._require_initialized()
        if isinstance(reference, str):
            location = self._world.location(reference)
            coordinate = location.coordinate
            scene = location.identity
        else:
            coordinate = _coordinate_reference(reference)
            location = self._try_location(coordinate)
            scene = (
                location.identity
                if location
                else self._world.terrain_zone_at(coordinate)
            )
        terrain = self._world.terrain_at(coordinate)
        altitude = self._world.altitude(coordinate)
        try:
            environment = self._environment_by_name[terrain]
        except KeyError as exc:
            raise BattlefieldError(
                f"地表地形没有对应战场环境：{terrain}"
            ) from exc
        return CombatFieldSpec(
            environment_id=environment.identity,
            scene=scene,
            origin="地表",
            coordinate=(coordinate.x, coordinate.y),
            altitude=altitude,
            terrain=terrain,
        )

    def surface_at(self, x: int, y: int) -> CombatFieldSpec:
        """解析未登记地点也可使用的地表战场。"""

        return self.surface((x, y))

    def _try_location(self, coordinate):
        try:
            return self._world.location(coordinate)
        except WorldDataError:
            return None

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


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BattlefieldError(f"{label}必须是非空字符串")
    return value.strip()


def _coordinate_reference(value: LocationReference) -> SurfaceCoordinate:
    if isinstance(value, SurfaceCoordinate):
        return value
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return _coordinate(value)
    raise BattlefieldError("地表坐标必须是 (x, y) 或 SurfaceCoordinate")


def _coordinate(value: Any):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise BattlefieldError("地表坐标必须包含 x 和 y")
    x, y = value
    if isinstance(x, bool) or not isinstance(x, int) or isinstance(y, bool) or not isinstance(y, int):
        raise BattlefieldError("地表坐标必须是整数")
    return SurfaceCoordinate(x=x, y=y)


__all__ = ["BattlefieldService"]
