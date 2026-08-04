"""只解释正式世界 JSON 的公共微服务。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from game.core.data import JsonDataService

from .contracts import (
    AltitudeRange,
    LocationDefinition,
    LocationFeatureDefinition,
    LocationReference,
    RegionDefinition,
    RegionTerrainDefinition,
    RoadDefinition,
    SurfaceBounds,
    SurfaceCoordinate,
    SurfacePoint,
    WorldDataError,
    WorldDefinition,
    WorldStatus,
)


class WorldService:
    """提供世界、地点、地势与道路的不可变事实。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._world: WorldDefinition | None = None
        self._regions: dict[str, RegionDefinition] = {}
        self._features: dict[str, LocationFeatureDefinition] = {}
        self._locations: dict[str, LocationDefinition] = {}
        self._locations_by_coordinate: dict[SurfaceCoordinate, LocationDefinition] = {}
        self._roads: tuple[RoadDefinition, ...] = ()
        self._terrain: tuple[tuple[int, ...], ...] = ()
        self._terrain_resolution = 0

    def initialize(self) -> WorldStatus:
        if self._world is not None:
            raise RuntimeError("世界微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于世界微服务启动")

        worlds = self._data.entities("世界")
        if len(worlds) != 1:
            raise WorldDataError("当前世界服务要求且只允许一个世界")
        identity, raw_world = next(iter(worlds.items()))
        _strict_fields(
            raw_world,
            {
                "道路",
                "出生地",
                "说明",
                "行程规则",
            },
            "世界",
        )
        road_types = _strings(raw_world.get("道路", ()), "世界道路")
        birthplace = _text(raw_world.get("出生地"), "世界出生地")

        bounds, altitude_range, meters_per_grid = self._load_terrain()
        self._features = self._load_features()
        self._regions = self._load_regions(bounds)
        self._validate_region_partition(bounds)
        self._locations = self._load_locations(bounds)
        self._locations_by_coordinate = {
            location.coordinate: location for location in self._locations.values()
        }
        if birthplace not in self._locations:
            raise WorldDataError(f"出生地不存在：{birthplace}")
        self._roads = self._load_roads(road_types, bounds)
        self._world = WorldDefinition(
            identity=identity,
            description=_text(raw_world.get("说明"), "世界说明"),
            birthplace=birthplace,
            bounds=bounds,
            altitude_range=altitude_range,
            meters_per_grid=meters_per_grid,
            road_types=road_types,
            travel_rule=_text(raw_world.get("行程规则"), "世界行程规则"),
        )
        return self.status()

    def status(self) -> WorldStatus:
        return WorldStatus(
            initialized=self._world is not None,
            world_count=1 if self._world is not None else 0,
            region_count=len(self._regions),
            location_count=len(self._locations),
            road_count=len(self._roads),
            feature_count=len(self._features),
        )

    def world(self) -> WorldDefinition:
        if self._world is None:
            raise RuntimeError("世界微服务尚未初始化")
        return self._world

    def birthplace(self) -> LocationDefinition:
        return self.location(self.world().birthplace)

    def regions(self) -> tuple[RegionDefinition, ...]:
        self.world()
        return tuple(self._regions.values())

    def region(self, identity: str) -> RegionDefinition:
        self.world()
        key = _identity(identity, "区域")
        try:
            return self._regions[key]
        except KeyError as exc:
            raise WorldDataError(f"区域不存在：{key}") from exc

    def region_at(self, x: int | SurfaceCoordinate, y: int | None = None) -> RegionDefinition:
        """返回任意地表 xy 所属的区域。"""

        self.world()
        coordinate = _coordinate_arguments(x, y, "区域坐标")
        if not self.world().bounds.contains(coordinate):
            raise WorldDataError(
                f"坐标超出世界边界：({coordinate.x}, {coordinate.y})"
            )
        for region in self._regions.values():
            if region.bounds.contains(coordinate):
                return region
        raise WorldDataError(
            f"地表坐标未归属区域：({coordinate.x}, {coordinate.y})"
        )

    def locations(self) -> tuple[LocationDefinition, ...]:
        self.world()
        return tuple(self._locations.values())

    def features(self) -> tuple[LocationFeatureDefinition, ...]:
        self.world()
        return tuple(self._features.values())

    def location(self, reference: LocationReference) -> LocationDefinition:
        self.world()
        if isinstance(reference, str):
            key = _identity(reference, "地点")
            try:
                return self._locations[key]
            except KeyError as exc:
                raise WorldDataError(f"地点不存在：{key}") from exc
        coordinate = _coordinate_reference(reference, "地点坐标")
        try:
            return self._locations_by_coordinate[coordinate]
        except KeyError as exc:
            raise WorldDataError(
                f"该坐标不是登记地点：({coordinate.x}, {coordinate.y})"
            ) from exc

    def location_at(self, x: int, y: int) -> LocationDefinition:
        return self.location(SurfaceCoordinate(x=x, y=y))

    def roads(self) -> tuple[RoadDefinition, ...]:
        self.world()
        return self._roads

    def altitude(self, coordinate: SurfaceCoordinate) -> int:
        world = self.world()
        return self._terrain_altitude(world.bounds, coordinate)

    def terrain_at(self, x: int | SurfaceCoordinate, y: int | None = None) -> str:
        """只按区域地形分区解析任意 xy 的战场地形。"""

        self.world()
        coordinate = _coordinate_arguments(x, y, "地形坐标")
        self.altitude(coordinate)
        region = self.region_at(coordinate)
        return _region_terrain(region, coordinate).terrain

    def terrain_zone_at(
        self, x: int | SurfaceCoordinate, y: int | None = None
    ) -> str:
        """返回地形分区或地点名称，供战场展示场景使用。"""

        self.world()
        coordinate = _coordinate_arguments(x, y, "地形分区坐标")
        self.altitude(coordinate)
        location = self._locations_by_coordinate.get(coordinate)
        if location is not None:
            return location.identity
        region = self.region_at(coordinate)
        for partition in region.terrain_partitions:
            if partition.bounds.contains(coordinate):
                return partition.name
        return region.identity

    def _terrain_altitude(
        self,
        bounds: SurfaceBounds,
        coordinate: SurfaceCoordinate,
    ) -> int:
        if not bounds.contains(coordinate):
            raise WorldDataError(
                f"坐标超出世界边界：({coordinate.x}, {coordinate.y})"
            )
        resolution = self._terrain_resolution
        x_offset = coordinate.x - bounds.x_min
        y_offset = coordinate.y - bounds.y_min
        if x_offset % resolution or y_offset % resolution:
            raise WorldDataError(
                f"坐标不符合地势分辨率 {resolution}："
                f"({coordinate.x}, {coordinate.y})"
            )
        return self._terrain[y_offset // resolution][x_offset // resolution]

    def surface_point(self, coordinate: SurfaceCoordinate) -> SurfacePoint:
        return SurfacePoint(coordinate=coordinate, altitude=self.altitude(coordinate))

    def _load_terrain(
        self,
    ) -> tuple[SurfaceBounds, AltitudeRange, int]:
        terrain_dataset = self._data.dataset("地势")
        if len(terrain_dataset) != 1:
            raise WorldDataError("当前世界要求且只允许一份地势数据")
        terrain_name, raw = next(iter(terrain_dataset.items()))
        _strict_fields(
            raw,
            {
                "分辨率",
                "高度单位",
                "海平面",
                "坐标边界",
                "海拔范围",
                "水平每格米数",
                "地表高度",
            },
            f"地势 {terrain_name}",
        )
        resolution = _positive_int(raw.get("分辨率"), "地势分辨率")
        bounds = _bounds(raw.get("坐标边界"), "地势坐标边界")
        altitude_range = _altitude_range(raw.get("海拔范围"), "地势海拔范围")
        meters_per_grid = _positive_int(
            raw.get("水平每格米数"), "地势水平每格米数"
        )
        if _text(raw.get("高度单位"), "地势高度单位") != "米":
            raise WorldDataError("地势高度单位必须是米")
        if _integer(raw.get("海平面"), "地势海平面") != 0:
            raise WorldDataError("当前世界地势海平面必须是 0 米")
        rows = _sequence(raw.get("地表高度"), "地表高度")
        expected_rows = (bounds.y_max - bounds.y_min) // resolution + 1
        expected_columns = (bounds.x_max - bounds.x_min) // resolution + 1
        if len(rows) != expected_rows:
            raise WorldDataError("地势行数与坐标边界不一致")
        terrain: list[tuple[int, ...]] = []
        for row in rows:
            values = _sequence(row, "地表高度行")
            if len(values) != expected_columns:
                raise WorldDataError("地势列数与坐标边界不一致")
            terrain.append(tuple(_integer(value, "地表高度") for value in values))
        actual = AltitudeRange(
            minimum=min(min(row) for row in terrain),
            maximum=max(max(row) for row in terrain),
        )
        if actual != altitude_range:
            raise WorldDataError("地势海拔范围不是真实最小值与最大值")
        self._terrain = tuple(terrain)
        self._terrain_resolution = resolution
        return bounds, altitude_range, meters_per_grid

    def _load_features(self) -> dict[str, LocationFeatureDefinition]:
        definitions = self._data.dataset("世界定义")
        rows = _sequence(definitions.get("地点功能"), "地点功能定义")
        features: dict[str, LocationFeatureDefinition] = {}
        allowed_location_fields = {"道侣池", "敌人池", "灵植池", "灵矿池"}
        allowed_range_fields = {"单次遭遇敌人数"}
        for raw in rows:
            row = _mapping(raw, "地点功能")
            _strict_fields(row, {"名称", "要求"}, "地点功能")
            name = _text(row.get("名称"), "地点功能名称")
            requirements = _mapping(row.get("要求"), f"地点功能 {name} 要求")
            _strict_fields(
                requirements,
                {"非空字段", "正数范围字段"},
                f"地点功能 {name} 要求",
            )
            nonempty_fields = _strings(
                requirements.get("非空字段", ()), f"地点功能 {name} 非空字段"
            )
            positive_range_fields = _strings(
                requirements.get("正数范围字段", ()),
                f"地点功能 {name} 正数范围字段",
            )
            if not set(nonempty_fields) <= allowed_location_fields:
                raise WorldDataError(f"地点功能 {name} 引用未知非空字段")
            if not set(positive_range_fields) <= allowed_range_fields:
                raise WorldDataError(f"地点功能 {name} 引用未知正数范围字段")
            if name in features:
                raise WorldDataError(f"地点功能重复：{name}")
            features[name] = LocationFeatureDefinition(
                name=name,
                nonempty_fields=nonempty_fields,
                positive_range_fields=positive_range_fields,
            )
        if not features:
            raise WorldDataError("地点功能定义不能为空")
        return features

    def _load_regions(self, world_bounds: SurfaceBounds) -> dict[str, RegionDefinition]:
        regions: dict[str, RegionDefinition] = {}
        for identity, raw in self._data.entities("区域").items():
            _strict_fields(
                raw,
                {"坐标范围", "类别", "地形分区", "说明"},
                f"区域 {identity}",
            )
            bounds = _bounds(raw.get("坐标范围"), f"区域 {identity} 坐标范围")
            values = [
                self._terrain_altitude(world_bounds, SurfaceCoordinate(x, y))
                for y in range(bounds.y_min, bounds.y_max + 1, self._terrain_resolution)
                for x in range(bounds.x_min, bounds.x_max + 1, self._terrain_resolution)
            ]
            actual = AltitudeRange(min(values), max(values))
            partitions = _load_terrain_partitions(
                raw.get("地形分区"), bounds, identity
            )
            regions[identity] = RegionDefinition(
                identity=identity,
                category=_text(raw.get("类别"), f"区域 {identity} 类别"),
                bounds=bounds,
                altitude_range=actual,
                terrain_partitions=partitions,
                description=_text(raw.get("说明"), f"区域 {identity} 说明"),
            )
        return regions

    def _validate_region_partition(self, world_bounds: SurfaceBounds) -> None:
        for y in range(world_bounds.y_min, world_bounds.y_max + 1):
            for x in range(world_bounds.x_min, world_bounds.x_max + 1):
                coordinate = SurfaceCoordinate(x, y)
                owners = tuple(
                    region.identity
                    for region in self._regions.values()
                    if region.bounds.contains(coordinate)
                )
                if len(owners) != 1:
                    raise WorldDataError(
                        f"地表坐标必须唯一属于一个区域：({x}, {y}) -> {owners}"
                    )

    def _load_locations(self, world_bounds: SurfaceBounds) -> dict[str, LocationDefinition]:
        locations: dict[str, LocationDefinition] = {}
        occupied: dict[SurfaceCoordinate, str] = {}
        region_by_location = self._location_regions()
        for identity, raw in self._data.entities("地点").items():
            _strict_fields(
                raw,
                {
                    "坐标",
                    "地点类型",
                    "灵植池",
                    "灵矿池",
                    "说明",
                    "可用功能",
                    "道侣池",
                    "敌人池",
                    "单次遭遇敌人数",
                },
                f"地点 {identity}",
            )
            coordinate = _coordinate(raw.get("坐标"), f"地点 {identity} 坐标")
            if not world_bounds.contains(coordinate):
                raise WorldDataError(f"地点 {identity} 超出世界边界")
            if previous := occupied.get(coordinate):
                raise WorldDataError(f"地点坐标重复：{previous} 与 {identity}")
            try:
                region_name = region_by_location[identity]
                region = self._regions[region_name]
            except KeyError as exc:
                raise WorldDataError(f"地点 {identity} 的目录区域不存在") from exc
            if not region.bounds.contains(coordinate):
                raise WorldDataError(f"地点 {identity} 超出所属区域 {region_name}")
            occupied[coordinate] = identity
            encounter = _pair(raw.get("单次遭遇敌人数", (0, 0)), "单次遭遇敌人数")
            available_features = _strings(raw.get("可用功能", ()), "可用功能")
            unknown_features = set(available_features) - set(self._features)
            if unknown_features:
                raise WorldDataError(
                    f"地点 {identity} 使用未知功能：{'、'.join(sorted(unknown_features))}"
                )
            self._validate_location_features(identity, raw, available_features)
            locations[identity] = LocationDefinition(
                identity=identity,
                region=region_name,
                coordinate=coordinate,
                altitude=self._terrain_altitude(world_bounds, coordinate),
                location_type=_text(raw.get("地点类型"), f"地点 {identity} 类型"),
                terrain=_region_terrain(region, coordinate).terrain,
                description=_text(raw.get("说明"), f"地点 {identity} 说明"),
                available_features=available_features,
                plant_pools=_strings(raw.get("灵植池", ()), "灵植池"),
                mineral_pools=_strings(raw.get("灵矿池", ()), "灵矿池"),
                companion_pools=_strings(raw.get("道侣池", ()), "道侣池"),
                enemy_pools=_strings(raw.get("敌人池", ()), "敌人池"),
                encounter_count=encounter,
            )
        return locations

    def _validate_location_features(
        self,
        identity: str,
        raw: Mapping[str, Any],
        available_features: tuple[str, ...],
    ) -> None:
        feature_names = set(available_features)
        field_owners: dict[str, set[str]] = {}
        for feature in self._features.values():
            for field in (*feature.nonempty_fields, *feature.positive_range_fields):
                field_owners.setdefault(field, set()).add(feature.name)
            if feature.name not in feature_names:
                continue
            for field in feature.nonempty_fields:
                value = raw.get(field)
                if not _sequence(value, f"地点 {identity}.{field}"):
                    raise WorldDataError(
                        f"地点 {identity} 开放 {feature.name} 时 {field} 不能为空"
                    )
            for field in feature.positive_range_fields:
                lower, _ = _pair(raw.get(field), f"地点 {identity}.{field}")
                if lower < 1:
                    raise WorldDataError(
                        f"地点 {identity} 开放 {feature.name} 时 {field} 必须为正数范围"
                    )
        for field, owners in field_owners.items():
            value = raw.get(field)
            populated = bool(value) and value != (0, 0)
            if populated and not (owners & feature_names):
                raise WorldDataError(
                    f"地点 {identity} 未开放对应功能却配置了 {field}"
                )

    def _location_regions(self) -> dict[str, str]:
        result = {
            identity: self._data.entity_record("地点", identity).directory_owner
            for identity in self._data.entities("地点")
        }
        missing = sorted(identity for identity, owner in result.items() if not owner)
        if missing:
            raise WorldDataError(f"地点缺少目录归属：{'、'.join(missing)}")
        unknown = sorted(set(result.values()) - set(self._regions))
        if unknown:
            raise WorldDataError(f"地点引用未知区域目录：{'、'.join(unknown)}")
        return result

    def _load_roads(
        self,
        road_types: tuple[str, ...],
        world_bounds: SurfaceBounds,
    ) -> tuple[RoadDefinition, ...]:
        datasets = self._data.dataset("道路")
        if set(datasets) != set(road_types):
            raise WorldDataError("世界登记道路与道路数据集不一致")
        roads: list[RoadDefinition] = []
        for road_type in road_types:
            for raw in _sequence(datasets[road_type], f"道路 {road_type}"):
                mapping = _mapping(raw, f"道路 {road_type}")
                _strict_fields(
                    mapping,
                    {"起点", "终点", "途经坐标"},
                    f"道路 {road_type}",
                )
                start = _text(mapping.get("起点"), "道路起点")
                destination = _text(mapping.get("终点"), "道路终点")
                if start not in self._locations or destination not in self._locations:
                    raise WorldDataError(f"道路端点不存在：{start} -> {destination}")
                coordinates = tuple(
                    _coordinate(value, "道路途经坐标")
                    for value in _sequence(mapping.get("途经坐标"), "道路途经坐标")
                )
                if len(coordinates) < 1:
                    raise WorldDataError(f"道路坐标不足：{start} -> {destination}")
                if any(not world_bounds.contains(value) for value in coordinates):
                    raise WorldDataError(f"道路坐标超出世界：{start} -> {destination}")
                roads.append(
                    RoadDefinition(
                        road_type=road_type,
                        start=start,
                        destination=destination,
                        coordinates=coordinates,
                    )
                )
        return tuple(roads)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorldDataError(f"{label} 必须是对象")
    return value


def _strict_fields(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    missing = allowed - set(value)
    if unknown or missing:
        parts = []
        if unknown:
            parts.append("未知字段 " + "、".join(sorted(unknown)))
        if missing:
            parts.append("缺少字段 " + "、".join(sorted(missing)))
        raise WorldDataError(f"{label}字段不完整：{'；'.join(parts)}")


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise WorldDataError(f"{label} 必须是列表")
    return value


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorldDataError(f"{label} 必须是整数")
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _integer(value, label)
    if result < 1:
        raise WorldDataError(f"{label} 必须大于 0")
    return result


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise WorldDataError(f"{label} 不能为空")
    return result


def _identity(value: str, label: str) -> str:
    return _text(value, f"{label}身份")


def _strings(value: Any, label: str) -> tuple[str, ...]:
    values = tuple(_text(item, label) for item in _sequence(value, label))
    if len(values) != len(set(values)):
        raise WorldDataError(f"{label} 不能重复")
    return values


def _pair(value: Any, label: str) -> tuple[int, int]:
    values = _sequence(value, label)
    if len(values) != 2:
        raise WorldDataError(f"{label} 必须包含两个整数")
    lower, upper = (_integer(item, label) for item in values)
    if lower < 0 or upper < lower:
        raise WorldDataError(f"{label} 范围无效")
    return lower, upper


def _coordinate(value: Any, label: str) -> SurfaceCoordinate:
    values = _sequence(value, label)
    if len(values) != 2:
        raise WorldDataError(f"{label} 必须包含两个整数")
    x, y = (_integer(item, label) for item in values)
    return SurfaceCoordinate(x=x, y=y)


def _coordinate_reference(value: Any, label: str) -> SurfaceCoordinate:
    if isinstance(value, SurfaceCoordinate):
        return value
    return _coordinate(value, label)


def _coordinate_arguments(
    x: int | SurfaceCoordinate, y: int | None, label: str
) -> SurfaceCoordinate:
    if isinstance(x, SurfaceCoordinate):
        if y is not None:
            raise WorldDataError(f"{label}不能同时传入坐标对象和 y")
        return x
    if y is None:
        raise WorldDataError(f"{label}必须同时包含 x 和 y")
    return _coordinate((x, y), label)


def _load_terrain_partitions(
    value: Any, region_bounds: SurfaceBounds, region_name: str
) -> tuple[RegionTerrainDefinition, ...]:
    rows = _sequence(value, f"区域 {region_name} 地形分区")
    partitions: list[RegionTerrainDefinition] = []
    for raw in rows:
        mapping = _mapping(raw, f"区域 {region_name} 地形分区")
        _strict_fields(
            mapping,
            {"名称", "坐标范围", "地形"},
            f"区域 {region_name} 地形分区",
        )
        name = _text(mapping.get("名称"), f"区域 {region_name} 地形分区名称")
        bounds = _bounds(
            mapping.get("坐标范围"), f"区域 {region_name} 地形分区 {name} 坐标范围"
        )
        terrain = _text(
            mapping.get("地形"), f"区域 {region_name} 地形分区 {name} 地形"
        )
        if not (
            region_bounds.contains(SurfaceCoordinate(bounds.x_min, bounds.y_min))
            and region_bounds.contains(SurfaceCoordinate(bounds.x_max, bounds.y_max))
        ):
            raise WorldDataError(f"区域 {region_name} 地形分区 {name} 超出区域范围")
        if any(
            _bounds_overlap(bounds, existing.bounds) for existing in partitions
        ):
            raise WorldDataError(f"区域 {region_name} 地形分区重叠：{name}")
        if any(name == existing.name for existing in partitions):
            raise WorldDataError(f"区域 {region_name} 地形分区重名：{name}")
        partitions.append(
            RegionTerrainDefinition(name=name, bounds=bounds, terrain=terrain)
        )
    if not partitions:
        raise WorldDataError(f"区域 {region_name} 地形分区不能为空")
    for y in range(region_bounds.y_min, region_bounds.y_max + 1):
        for x in range(region_bounds.x_min, region_bounds.x_max + 1):
            coordinate = SurfaceCoordinate(x, y)
            owners = tuple(
                partition.name
                for partition in partitions
                if partition.bounds.contains(coordinate)
            )
            if len(owners) != 1:
                raise WorldDataError(
                    f"区域 {region_name} 坐标必须唯一属于一个地形分区："
                    f"({x}, {y}) -> {owners}"
                )
    return tuple(partitions)


def _region_terrain(
    region: RegionDefinition, coordinate: SurfaceCoordinate
) -> RegionTerrainDefinition:
    for partition in region.terrain_partitions:
        if partition.bounds.contains(coordinate):
            return partition
    raise WorldDataError(
        f"区域 {region.identity} 坐标没有地形分区："
        f"({coordinate.x}, {coordinate.y})"
    )


def _bounds_overlap(left: SurfaceBounds, right: SurfaceBounds) -> bool:
    return not (
        left.x_max < right.x_min
        or right.x_max < left.x_min
        or left.y_max < right.y_min
        or right.y_max < left.y_min
    )


def _bounds(value: Any, label: str) -> SurfaceBounds:
    mapping = _mapping(value, label)
    if set(mapping) != {"x轴", "y轴"}:
        raise WorldDataError(f"{label} 只能包含 x轴 和 y轴")
    x_min, x_max = _pair(mapping["x轴"], f"{label}.x轴")
    y_min, y_max = _pair(mapping["y轴"], f"{label}.y轴")
    return SurfaceBounds(x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max)


def _altitude_range(value: Any, label: str) -> AltitudeRange:
    values = _sequence(value, label)
    if len(values) != 2:
        raise WorldDataError(f"{label} 必须包含两个整数")
    minimum, maximum = (_integer(item, label) for item in values)
    if maximum < minimum:
        raise WorldDataError(f"{label} 范围无效")
    return AltitudeRange(minimum=minimum, maximum=maximum)


__all__ = ["WorldService"]
