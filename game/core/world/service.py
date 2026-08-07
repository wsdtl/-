"""由正式世界 JSON 驱动的地点查询服务。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from game.core.data import JsonDataError, JsonDataService

from .contracts import LocationQuery, LocationView, WorldStatus


class WorldService:
    """解析地点、区域、地形和地表海拔，不持有玩家位置。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._initialized = False
        self._locations: Mapping[str, Mapping[str, object]] = {}
        self._regions: Mapping[str, Mapping[str, object]] = {}
        self._locations_by_xy: dict[
            tuple[int, int], tuple[str, Mapping[str, object]]
        ] = {}
        self._feature_contents: dict[str, tuple[str, ...]] = {}
        self._surface: tuple[tuple[int, ...], ...] = ()
        self._bounds: tuple[int, int, int, int] = (0, 0, 0, 0)

    def initialize(self) -> WorldStatus:
        if self._initialized:
            raise RuntimeError("世界地点服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于世界地点服务启动")

        self._locations = self._data.entities("地点")
        self._regions = self._data.entities("区域")
        definitions = self._data.dataset("世界定义").get("地点功能")
        self._feature_contents = _feature_contents(definitions)
        self._locations_by_xy = {}
        for location_name, raw in self._locations.items():
            xy = _xy(raw.get("坐标"), f"地点 {location_name}.坐标")
            if xy in self._locations_by_xy:
                raise JsonDataError(f"地点坐标重复：{xy}")
            self._locations_by_xy[xy] = (location_name, raw)
        terrain = self._data.dataset("地势").get("地势")
        if not isinstance(terrain, Mapping):
            raise JsonDataError("地势数据必须是对象")
        self._surface = _surface_grid(terrain.get("地表高度"))
        self._bounds = _xy_bounds(terrain.get("坐标边界"))
        if len(self._surface) != self._bounds[3] - self._bounds[2] + 1:
            raise JsonDataError("地势地表高度的 y 轴尺寸与坐标边界不一致")
        if any(
            len(row) != self._bounds[1] - self._bounds[0] + 1 for row in self._surface
        ):
            raise JsonDataError("地势地表高度的 x 轴尺寸与坐标边界不一致")
        for location_name, raw in self._locations.items():
            xy = _xy(raw.get("坐标"), f"地点 {location_name}.坐标")
            terrain_name = self._terrain_at(self._region_at(xy), xy)
            self._require_pool(f"灵植-{terrain_name}", "物品")
            self._require_pool(f"灵矿-{terrain_name}", "物品")
            for function in _strings(raw.get("可用功能")):
                sections = self._feature_contents.get(function)
                if sections is None:
                    raise JsonDataError(
                        f"地点 {location_name} 使用未登记功能：{function}"
                    )
                for section in sections:
                    self._require_pool(f"{location_name}{section}", section)
        self._initialized = True
        return self.status()

    def status(self) -> WorldStatus:
        return WorldStatus(
            initialized=self._initialized,
            location_count=len(self._locations),
            region_count=len(self._regions),
            terrain_cell_count=sum(len(row) for row in self._surface),
        )

    def locate(self, query: LocationQuery) -> LocationView:
        self._require_initialized()
        location_name = str(query.location_name or "").strip()
        if bool(location_name) == (query.xy is not None):
            raise ValueError("地点查询必须只提供地点名或 xy")
        if location_name:
            raw = self._locations.get(location_name)
            if raw is None:
                raise JsonDataError(f"地点不存在：{location_name}")
            xy = _xy(raw.get("坐标"), f"地点 {location_name}.坐标")
        else:
            xy = _validate_xy(query.xy, self._bounds)
            location = self._location_at(xy)
            location_name, raw = location if location is not None else ("", {})
        region = self._region_at(xy)
        terrain = self._terrain_at(region, xy)
        functions = _strings(raw.get("可用功能"))
        content_sections = {
            section
            for function in functions
            for section in self._feature_contents[function]
        }
        plant_pool = (f"灵植-{terrain}",)
        mineral_pool = (f"灵矿-{terrain}",)
        companion_pool = (f"{location_name}道侣",) if location_name and "道侣" in content_sections else ()
        enemy_pool = (f"{location_name}敌人",) if location_name and "敌人" in content_sections else ()
        return LocationView(
            location_name=location_name or str(raw.get("名称") or ""),
            xy=xy,
            location_type=str(raw.get("地点类型") or "野外地表"),
            region=region,
            terrain=terrain,
            altitude=self._altitude(xy),
            available_functions=functions,
            plant_pool=plant_pool,
            mineral_pool=mineral_pool,
            companion_pool=companion_pool,
            enemy_pool=enemy_pool,
            enemy_count=_numbers(raw.get("单次遭遇敌人数")),
        )

    def _location_at(self, xy: tuple[int, int]) -> tuple[str, Mapping[str, object]] | None:
        return self._locations_by_xy.get(xy)

    def _require_pool(self, file_id: str, section: str) -> None:
        try:
            self._data.pool_members((file_id,), section)
        except JsonDataError as exc:
            raise JsonDataError(f"派生资源池无效：{file_id} -> {section}") from exc

    def _region_at(self, xy: tuple[int, int]) -> str:
        matches = [
            name
            for name, raw in self._regions.items()
            if _in_range(xy, raw.get("坐标范围"))
        ]
        if len(matches) != 1:
            raise JsonDataError(f"xy 必须且只能属于一个区域：{xy} -> {matches}")
        return matches[0]

    def _altitude(self, xy: tuple[int, int]) -> int:
        x, y = xy
        return self._surface[y - self._bounds[2]][x - self._bounds[0]]

    def _terrain_at(self, region: str, xy: tuple[int, int]) -> str:
        raw = self._regions[region]
        parts = raw.get("地形分区")
        if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes)):
            raise JsonDataError(f"区域缺少地形分区：{region}")
        matches = [
            part
            for part in parts
            if isinstance(part, Mapping) and _in_range(xy, part.get("坐标范围"))
        ]
        if len(matches) != 1:
            raise JsonDataError(
                f"xy 必须且只能属于一个地形分区：{xy} -> {region}"
            )
        terrain = matches[0].get("地形")
        if not isinstance(terrain, str) or not terrain:
            raise JsonDataError(f"地形分区缺少地形名称：{region} -> {xy}")
        return terrain

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("世界地点服务尚未初始化")


def _surface_grid(value: object) -> tuple[tuple[int, ...], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise JsonDataError("地势.地表高度必须是非空二维数组")
    rows: list[tuple[int, ...]] = []
    for row in value:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or not row:
            raise JsonDataError("地势.地表高度必须是非空二维数组")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in row):
            raise JsonDataError("地势.地表高度只能包含整数")
        rows.append(tuple(row))
    return tuple(rows)


def _xy_bounds(value: object) -> tuple[int, int, int, int]:
    if not isinstance(value, Mapping):
        raise JsonDataError("地势.坐标边界必须是对象")
    x_axis = value.get("x轴")
    y_axis = value.get("y轴")
    if not _ordered_pair(x_axis) or not _ordered_pair(y_axis):
        raise JsonDataError("地势.坐标边界必须分别声明 x轴 和 y轴")
    return (x_axis[0], x_axis[1], y_axis[0], y_axis[1])


def _xy(value: object, label: str) -> tuple[int, int]:
    if not _valid_pair(value):
        raise JsonDataError(f"{label}必须是两个整数")
    return (value[0], value[1])


def _validate_xy(
    value: tuple[int, int] | None,
    bounds: tuple[int, int, int, int],
) -> tuple[int, int]:
    xy = _xy(value, "xy")
    if not (
        bounds[0] <= xy[0] <= bounds[1]
        and bounds[2] <= xy[1] <= bounds[3]
    ):
        raise JsonDataError(f"xy 超出世界边界：{xy}")
    return xy


def _valid_pair(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    )


def _ordered_pair(value: object) -> bool:
    return _valid_pair(value) and value[0] <= value[1]


def _in_range(xy: tuple[int, int], value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    return _axis_contains(xy[0], value.get("x轴")) and _axis_contains(
        xy[1], value.get("y轴")
    )


def _axis_contains(value: int, bounds: object) -> bool:
    return _ordered_pair(bounds) and bounds[0] <= value <= bounds[1]


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value)


def _numbers(value: object) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(int(item) for item in value)


def _feature_contents(value: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError("地点功能定义必须是字典列表")
    result: dict[str, tuple[str, ...]] = {}
    for raw in value:
        if not isinstance(raw, Mapping):
            raise JsonDataError("地点功能定义只能包含对象")
        name = str(raw.get("名称") or "").strip()
        if not name or name in result:
            raise JsonDataError("地点功能名称不能为空或重复")
        contents = _strings(raw.get("同目录内容"))
        if any(section not in {"道侣", "敌人"} for section in contents):
            raise JsonDataError(f"地点功能使用未知同目录内容：{name} -> {contents}")
        result[name] = contents
    return result


__all__ = ["WorldService"]
