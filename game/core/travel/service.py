"""按正式路网自动选择最优行程并生成叙事。"""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from game.core.data import JsonDataService
from game.core.world import (
    RoadDefinition,
    SurfaceCoordinate,
    SurfacePoint,
    WorldService,
)

from .contracts import (
    TravelError,
    TravelMetrics,
    TravelPlan,
    TravelRealmEffects,
    TravelRequest,
    TravelStatus,
)

METRIC_UNITS = MappingProxyType(
    {
        "水平距离": "米",
        "道路段数": "段",
        "最低海拔": "米",
        "最高海拔": "米",
        "累计爬升": "米",
        "累计下降": "米",
        "最大单步升高": "米",
        "最大单步降低": "米",
        "最大上坡千分比": "千分比",
        "最大下坡千分比": "千分比",
        "折算路程": "米",
    }
)
ROUTE_SORT_METRICS = frozenset({"折算路程", "道路段数", "水平距离"})
TRAVEL_FACTS = frozenset(
    {
        "起点",
        "终点",
        "终点所属区域",
        "经由地点",
        "经由道路",
        "首段道路",
        "末段道路",
        "地势转折地点",
        "水平距离",
        "最低海拔",
        "最高海拔",
        "累计爬升",
        "累计下降",
        "折算路程",
    }
)


@dataclass(frozen=True)
class _RoadProfile:
    horizontal: float
    ascent: int
    descent: int
    adjusted: float


@dataclass(frozen=True)
class _DirectedRoad:
    road_type: str
    start: str
    destination: str
    coordinates: tuple[SurfaceCoordinate, ...]
    profile: _RoadProfile


class TravelService:
    """消费世界事实和行路 JSON，不保存人物位置。"""

    def __init__(self, data: JsonDataService, world: WorldService) -> None:
        self._data = data
        self._world = world
        self._metrics: tuple[str, ...] = ()
        self._sort_metrics: tuple[str, ...] = ()
        self._graph: dict[str, tuple[_DirectedRoad, ...]] = {}
        self._road_count = 0
        self._road_multipliers: dict[str, float] = {}
        self._horizontal_weight = 0.0
        self._ascent_weight = 0.0
        self._descent_weight = 0.0
        self._diagonal_multiplier = 0.0
        self._allowed_steps: frozenset[tuple[int, int]] = frozenset()
        self._must_include_start = True
        self._must_include_destination = True
        self._allow_repeated_coordinates = False
        self._default_bidirectional = True
        self._require_connected = True
        self._narrative_order: tuple[str, ...] = ()
        self._realm_effects: TravelRealmEffects | None = None
        self._display: Mapping[str, Any] | None = None

    def initialize(self) -> TravelStatus:
        if self._display is not None:
            raise RuntimeError("行程微服务已经初始化")
        if not self._world.status().initialized:
            raise RuntimeError("世界微服务必须先于行程微服务启动")
        definitions = self._data.dataset("行路定义")
        rules = self._data.dataset("行路规则")
        try:
            raw_rule = _mapping(rules[self._world.world().travel_rule], "行程规则")
        except KeyError as exc:
            raise TravelError("世界引用的行程规则不存在") from exc
        _strict_fields(
            raw_rule,
            {
                "道路来源",
                "地势来源",
                "水平尺度来源",
                "展示来源",
                "道路坐标",
                "路网要求",
                "自动选路",
                "路程折算",
                "道路折算倍率",
                "行程事实",
                "境界影响",
            },
            "行程规则",
        )
        self._validate_sources(raw_rule)
        self._metrics = self._load_metrics(definitions)
        coordinate_rule = _mapping(raw_rule.get("道路坐标"), "道路坐标规则")
        _strict_fields(
            coordinate_rule,
            {
                "维数",
                "必须包含起点",
                "必须包含终点",
                "允许重复坐标",
                "默认双向",
                "允许相邻步",
                "斜向距离倍率",
            },
            "道路坐标规则",
        )
        if _positive_int(coordinate_rule.get("维数"), "道路坐标维数") != 2:
            raise TravelError("道路坐标维数必须是 2")
        self._must_include_start = _boolean(
            coordinate_rule.get("必须包含起点"), "必须包含起点"
        )
        self._must_include_destination = _boolean(
            coordinate_rule.get("必须包含终点"), "必须包含终点"
        )
        self._allow_repeated_coordinates = _boolean(
            coordinate_rule.get("允许重复坐标"), "允许重复坐标"
        )
        self._default_bidirectional = _boolean(
            coordinate_rule.get("默认双向"), "默认双向"
        )
        self._allowed_steps = self._load_allowed_steps(
            coordinate_rule.get("允许相邻步")
        )
        self._diagonal_multiplier = _positive_number(
            coordinate_rule.get("斜向距离倍率"), "斜向距离倍率"
        )
        conversion = _mapping(raw_rule.get("路程折算"), "路程折算")
        _strict_fields(
            conversion,
            {"水平每米", "上升每米", "下降每米"},
            "路程折算",
        )
        self._horizontal_weight = _positive_number(
            conversion.get("水平每米"), "水平每米折算"
        )
        self._ascent_weight = _positive_number(
            conversion.get("上升每米"), "上升每米折算"
        )
        self._descent_weight = _positive_number(
            conversion.get("下降每米"), "下降每米折算"
        )
        self._road_multipliers = self._load_road_multipliers(
            raw_rule.get("道路折算倍率")
        )
        if set(self._road_multipliers) != set(self._world.world().road_types):
            raise TravelError("道路折算倍率与世界道路不一致")
        self._load_network_rules(raw_rule)
        self._sort_metrics = self._load_sort_metrics(raw_rule)
        self._validate_travel_facts(raw_rule.get("行程事实"))
        self._realm_effects = self._load_realm_effects(raw_rule.get("境界影响"))
        display_name = _text(raw_rule.get("展示来源"), "行程展示来源")
        try:
            self._display = _mapping(
                self._data.dataset("行路展示")[display_name], "行程展示"
            )
        except KeyError as exc:
            raise TravelError(f"行程展示不存在：{display_name}") from exc
        self._load_display_contract(self._display)
        self._graph = self._build_graph(self._world.roads())
        self._road_count = len(self._world.roads())
        if self._require_connected:
            self._validate_connectivity()
        return self.status()

    def status(self) -> TravelStatus:
        return TravelStatus(
            initialized=self._display is not None,
            metric_count=len(self._metrics),
            road_count=self._road_count,
        )

    def realm_effects(self) -> TravelRealmEffects:
        self._require_initialized()
        assert self._realm_effects is not None
        return self._realm_effects

    def plan(self, request: TravelRequest) -> TravelPlan:
        self._require_initialized()
        start_location = self._world.location(request.start)
        destination_location = self._world.location(request.destination)
        start = start_location.identity
        destination = destination_location.identity
        if start == destination:
            raise TravelError("行程起点与终点不能相同")
        roads = self._find_route(start, destination)
        points = self._route_points(roads)
        metrics = self._metrics_for(roads, points)
        via_locations = tuple(road.destination for road in roads[:-1])
        turning = self._turning_location(roads, start, destination)
        narrative = self._narrative(
            start=start,
            destination=destination,
            via_locations=via_locations,
            roads=roads,
            turning=turning,
            metrics=metrics,
        )
        return TravelPlan(
            start=start,
            destination=destination,
            destination_region=destination_location.region,
            via_locations=via_locations,
            road_types=tuple(road.road_type for road in roads),
            terrain_turning_location=turning,
            points=points,
            metrics=metrics,
            narrative=narrative,
        )

    def _build_graph(
        self,
        roads: tuple[RoadDefinition, ...],
    ) -> dict[str, tuple[_DirectedRoad, ...]]:
        graph: dict[str, list[_DirectedRoad]] = {
            location.identity: [] for location in self._world.locations()
        }
        for road in roads:
            coordinates = self._validated_coordinates(road)
            forward = self._directed_road(
                road.road_type, road.start, road.destination, coordinates
            )
            graph[forward.start].append(forward)
            if self._default_bidirectional:
                backward = self._directed_road(
                    road.road_type,
                    road.destination,
                    road.start,
                    tuple(reversed(coordinates)),
                )
                graph[backward.start].append(backward)
        return {
            name: tuple(sorted(values, key=lambda value: (value.destination, value.road_type)))
            for name, values in graph.items()
        }

    def _validated_coordinates(
        self,
        road: RoadDefinition,
    ) -> tuple[SurfaceCoordinate, ...]:
        coordinates = list(road.coordinates)
        start = self._world.location(road.start).coordinate
        destination = self._world.location(road.destination).coordinate
        if self._must_include_start and coordinates[0] != start:
            raise TravelError(f"道路起点坐标不一致：{road.start}")
        if not self._must_include_start and coordinates[0] != start:
            coordinates.insert(0, start)
        if self._must_include_destination and coordinates[-1] != destination:
            raise TravelError(f"道路终点坐标不一致：{road.destination}")
        if not self._must_include_destination and coordinates[-1] != destination:
            coordinates.append(destination)
        if not self._allow_repeated_coordinates and len(coordinates) != len(set(coordinates)):
            raise TravelError(f"道路存在重复坐标：{road.start} -> {road.destination}")
        for left, right in itertools.pairwise(coordinates):
            step = (right.x - left.x, right.y - left.y)
            if step not in self._allowed_steps:
                raise TravelError(
                    f"道路坐标使用未允许步长 {step}：{road.start} -> {road.destination}"
                )
        return tuple(coordinates)

    def _directed_road(
        self,
        road_type: str,
        start: str,
        destination: str,
        coordinates: tuple[SurfaceCoordinate, ...],
    ) -> _DirectedRoad:
        horizontal = 0.0
        ascent = 0
        descent = 0
        scale = self._world.world().meters_per_grid
        for left, right in itertools.pairwise(coordinates):
            diagonal = left.x != right.x and left.y != right.y
            horizontal += scale * (self._diagonal_multiplier if diagonal else 1.0)
            difference = self._world.altitude(right) - self._world.altitude(left)
            if difference > 0:
                ascent += difference
            else:
                descent -= difference
        adjusted = self._road_multipliers[road_type] * (
            horizontal * self._horizontal_weight
            + ascent * self._ascent_weight
            + descent * self._descent_weight
        )
        return _DirectedRoad(
            road_type=road_type,
            start=start,
            destination=destination,
            coordinates=coordinates,
            profile=_RoadProfile(
                horizontal=horizontal,
                ascent=ascent,
                descent=descent,
                adjusted=adjusted,
            ),
        )

    def _find_route(self, start: str, destination: str) -> tuple[_DirectedRoad, ...]:
        serial = itertools.count()
        zero = self._route_sort_key(0.0, 0, 0.0)
        queue: list[tuple[tuple[float, ...], int, str, float, int, float]] = [
            (zero, next(serial), start, 0.0, 0, 0.0)
        ]
        best: dict[str, tuple[float, ...]] = {start: zero}
        previous: dict[str, tuple[str, _DirectedRoad]] = {}
        while queue:
            cost, _, node, adjusted, segments, horizontal = heapq.heappop(queue)
            if cost != best.get(node):
                continue
            if node == destination:
                break
            for road in self._graph[node]:
                next_adjusted = adjusted + road.profile.adjusted
                next_segments = segments + 1
                next_horizontal = horizontal + road.profile.horizontal
                next_cost = self._route_sort_key(
                    next_adjusted,
                    next_segments,
                    next_horizontal,
                )
                if next_cost >= best.get(
                    road.destination,
                    tuple(math.inf for _ in self._sort_metrics),
                ):
                    continue
                best[road.destination] = next_cost
                previous[road.destination] = (node, road)
                heapq.heappush(
                    queue,
                    (
                        next_cost,
                        next(serial),
                        road.destination,
                        next_adjusted,
                        next_segments,
                        next_horizontal,
                    ),
                )
        if destination not in previous:
            raise TravelError(f"正式路网没有路线：{start} -> {destination}")
        route: list[_DirectedRoad] = []
        node = destination
        while node != start:
            node, road = previous[node]
            route.append(road)
        route.reverse()
        return tuple(route)

    def _route_sort_key(
        self,
        adjusted: float,
        segments: int,
        horizontal: float,
    ) -> tuple[float, ...]:
        values = {
            "折算路程": adjusted,
            "道路段数": float(segments),
            "水平距离": horizontal,
        }
        return tuple(values[name] for name in self._sort_metrics)

    def _route_points(self, roads: tuple[_DirectedRoad, ...]) -> tuple[SurfacePoint, ...]:
        coordinates: list[SurfaceCoordinate] = []
        for index, road in enumerate(roads):
            coordinates.extend(road.coordinates if index == 0 else road.coordinates[1:])
        return tuple(self._world.surface_point(value) for value in coordinates)

    def _metrics_for(
        self,
        roads: tuple[_DirectedRoad, ...],
        points: tuple[SurfacePoint, ...],
    ) -> TravelMetrics:
        horizontal = sum(road.profile.horizontal for road in roads)
        ascent = sum(road.profile.ascent for road in roads)
        descent = sum(road.profile.descent for road in roads)
        adjusted = sum(road.profile.adjusted for road in roads)
        step_up = 0
        step_down = 0
        uphill = 0.0
        downhill = 0.0
        scale = self._world.world().meters_per_grid
        for left, right in itertools.pairwise(points):
            difference = right.altitude - left.altitude
            dx = abs(right.coordinate.x - left.coordinate.x)
            dy = abs(right.coordinate.y - left.coordinate.y)
            step_distance = scale * (
                self._diagonal_multiplier if dx and dy else 1.0
            )
            if difference > 0:
                step_up = max(step_up, difference)
                uphill = max(uphill, difference / step_distance * 1000)
            else:
                step_down = max(step_down, -difference)
                downhill = max(downhill, -difference / step_distance * 1000)
        altitudes = tuple(point.altitude for point in points)
        return TravelMetrics(
            horizontal_distance=round(horizontal),
            road_segments=len(roads),
            minimum_altitude=min(altitudes),
            maximum_altitude=max(altitudes),
            total_ascent=ascent,
            total_descent=descent,
            maximum_step_up=step_up,
            maximum_step_down=step_down,
            maximum_uphill_per_mille=round(uphill, 3),
            maximum_downhill_per_mille=round(downhill, 3),
            adjusted_distance=round(adjusted),
        )

    @staticmethod
    def _turning_location(
        roads: tuple[_DirectedRoad, ...],
        start: str,
        destination: str,
    ) -> str:
        candidates = [
            road
            for road in roads
            if road.start not in {start, destination} and road.profile.ascent > 0
        ]
        if not candidates:
            return ""
        return max(candidates, key=lambda road: road.profile.ascent).start

    def _narrative(
        self,
        *,
        start: str,
        destination: str,
        via_locations: tuple[str, ...],
        roads: tuple[_DirectedRoad, ...],
        turning: str,
        metrics: TravelMetrics,
    ) -> str:
        display = self._require_initialized()
        narrative = _mapping(display.get("叙事"), "行程叙事")
        road_words = {
            _text(row.get("道路"), "道路措辞名称"): row
            for row in (
                _mapping(value, "道路措辞")
                for value in _sequence(display.get("道路措辞"), "道路措辞")
            )
        }
        first = roads[0]
        direction = self._direction_word(first.coordinates[0], first.coordinates[1])
        first_words = _mapping(road_words[first.road_type], "首段道路措辞")
        start_text = _text(narrative.get("起程"), "起程模板").format(
            起点=start,
            首段道路措辞=_text(first_words.get("起行"), "道路起行措辞").format(
                方向=direction
            ),
        )
        transitions = []
        for previous, current in itertools.pairwise(roads):
            if current.road_type == previous.road_type:
                continue
            current_words = _mapping(road_words[current.road_type], "转入道路措辞")
            transitions.append(_text(current_words.get("转入"), "道路转入措辞"))
        via_text = ""
        if via_locations:
            transition_text = ""
            if transitions:
                transition_text = "，" + "，再".join(transitions)
            via_text = _text(narrative.get("经由"), "经由模板").format(
                经由地点="、".join(via_locations),
                转入道路措辞=transition_text,
            )
        climb_word = self._threshold_word(
            display.get("爬升措辞"), "累计爬升上限", metrics.total_ascent
        )
        terrain_template = (
            narrative.get("地势有转折地点")
            if turning
            else narrative.get("地势无转折地点")
        )
        terrain_text = _text(terrain_template, "地势模板").format(
            地势转折地点=turning,
            爬升措辞=climb_word,
        )
        last_words = _mapping(road_words[roads[-1].road_type], "末段道路措辞")
        destination_text = _text(narrative.get("抵达"), "抵达模板").format(
            末段道路收束=_text(last_words.get("收束"), "道路收束措辞"),
            终点=destination,
        )
        distance = _mapping(display.get("距离"), "行程距离展示")
        meters_per_li = _positive_int(distance.get("每里米数"), "每里米数")
        step = _positive_int(distance.get("约数步长"), "里程约数步长")
        li = max(step, round(metrics.horizontal_distance / meters_per_li / step) * step)
        overview_key = "总览低地" if metrics.maximum_altitude <= 0 else "总览高地"
        altitude_word = self._threshold_word(
            display.get("海拔措辞"), "最高海拔上限", metrics.maximum_altitude
        )
        overview = _text(narrative.get(overview_key), "行程总览模板").format(
            里程=li,
            最高海拔=metrics.maximum_altitude,
            海拔措辞=altitude_word,
        )
        sections = {
            "起程": start_text,
            "经由": via_text
            or _text(narrative.get("没有经由地点", ""), "没有经由地点模板", allow_empty=True),
            "地势": terrain_text,
            "抵达": destination_text,
            "总览": overview,
        }
        return "\n".join(
            sections[name] for name in self._narrative_order if sections[name]
        )

    def _validate_sources(self, rule: Mapping[str, Any]) -> None:
        world = self._world.world()
        expected = {
            "道路来源": f"{world.identity}.道路",
            "地势来源": f"{world.identity}.地势",
            "水平尺度来源": f"{world.identity}.水平每格米数",
        }
        for field, value in expected.items():
            if _text(rule.get(field), field) != value:
                raise TravelError(f"{field}必须引用 {value}")

    def _load_metrics(self, definitions: Mapping[str, Any]) -> tuple[str, ...]:
        rows = _sequence(definitions.get("行程指标"), "行程指标")
        metrics: list[str] = []
        for raw in rows:
            row = _mapping(raw, "行程指标")
            _strict_fields(row, {"名称", "单位"}, "行程指标")
            name = _text(row.get("名称"), "行程指标名称")
            unit = _text(row.get("单位"), f"行程指标 {name} 单位")
            expected_unit = METRIC_UNITS.get(name)
            if expected_unit is None or unit != expected_unit:
                raise TravelError(f"行程指标不受支持或单位错误：{name} {unit}")
            metrics.append(name)
        if len(metrics) != len(set(metrics)) or set(metrics) != set(METRIC_UNITS):
            raise TravelError("行程指标必须与行程服务公共契约完整一致")
        return tuple(metrics)

    @staticmethod
    def _load_allowed_steps(value: Any) -> frozenset[tuple[int, int]]:
        steps = frozenset(
            _integer_pair(raw, "允许相邻步")
            for raw in _sequence(value, "允许相邻步")
        )
        if not steps or (0, 0) in steps:
            raise TravelError("允许相邻步不能为空且不能包含原地停留")
        return steps

    @staticmethod
    def _load_road_multipliers(value: Any) -> dict[str, float]:
        result: dict[str, float] = {}
        for raw in _sequence(value, "道路折算倍率"):
            row = _mapping(raw, "道路倍率")
            _strict_fields(row, {"道路", "倍率"}, "道路倍率")
            name = _text(row.get("道路"), "道路倍率名称")
            if name in result:
                raise TravelError(f"道路倍率重复：{name}")
            result[name] = _positive_number(row.get("倍率"), "道路倍率")
        return result

    def _load_network_rules(self, rule: Mapping[str, Any]) -> None:
        network = _mapping(rule.get("路网要求"), "路网要求")
        _strict_fields(network, {"全部地点连通", "没有路线"}, "路网要求")
        self._require_connected = _boolean(
            network.get("全部地点连通"), "全部地点连通"
        )
        if _text(network.get("没有路线"), "没有路线") != "数据错误":
            raise TravelError("当前行程契约只允许把无路线视为数据错误")

    @staticmethod
    def _load_sort_metrics(rule: Mapping[str, Any]) -> tuple[str, ...]:
        automatic = _mapping(rule.get("自动选路"), "自动选路")
        _strict_fields(automatic, {"玩家选择路线", "排序"}, "自动选路")
        if _boolean(automatic.get("玩家选择路线"), "玩家选择路线"):
            raise TravelError("自动行程服务不允许玩家直接选择道路")
        result = []
        for raw in _sequence(automatic.get("排序"), "自动选路排序"):
            row = _mapping(raw, "自动选路排序")
            _strict_fields(row, {"指标", "顺序"}, "自动选路排序")
            name = _text(row.get("指标"), "自动选路指标")
            if name not in ROUTE_SORT_METRICS:
                raise TravelError(f"自动选路不支持指标：{name}")
            if _text(row.get("顺序"), "自动选路顺序") != "升序":
                raise TravelError("自动选路当前只支持非负指标升序")
            result.append(name)
        if len(result) != len(set(result)) or set(result) != ROUTE_SORT_METRICS:
            raise TravelError("自动选路排序必须完整且不能重复")
        return tuple(result)

    @staticmethod
    def _validate_travel_facts(value: Any) -> None:
        facts = _strings(value, "行程事实")
        if set(facts) != TRAVEL_FACTS:
            raise TravelError("行程事实必须与 TravelPlan 输出完整一致")

    @staticmethod
    def _load_realm_effects(value: Any) -> TravelRealmEffects:
        raw = _mapping(value, "境界影响")
        fields = {
            "目的地可达",
            "道路可用",
            "赶路方式",
            "行程速度",
            "展示措辞",
        }
        _strict_fields(raw, fields, "境界影响")
        return TravelRealmEffects(
            destination_reachability=_boolean(raw["目的地可达"], "目的地可达"),
            road_availability=_boolean(raw["道路可用"], "道路可用"),
            travel_method=_boolean(raw["赶路方式"], "赶路方式"),
            travel_speed=_boolean(raw["行程速度"], "行程速度"),
            display_wording=_boolean(raw["展示措辞"], "展示措辞"),
        )

    def _load_display_contract(self, value: Mapping[str, Any]) -> None:
        _strict_fields(
            value,
            {"距离", "方向措辞", "道路措辞", "爬升措辞", "海拔措辞", "叙事"},
            "行程展示",
        )
        narrative = _mapping(value.get("叙事"), "行程叙事")
        required = {
            "顺序",
            "起程",
            "经由",
            "没有经由地点",
            "地势有转折地点",
            "地势无转折地点",
            "抵达",
            "总览高地",
            "总览低地",
        }
        _strict_fields(narrative, required, "行程叙事")
        order = _strings(narrative.get("顺序"), "行程叙事顺序")
        if set(order) != {"起程", "经由", "地势", "抵达", "总览"}:
            raise TravelError("行程叙事顺序必须完整且不能重复")
        self._narrative_order = order

    def _direction_word(
        self,
        start: SurfaceCoordinate,
        destination: SurfaceCoordinate,
    ) -> str:
        display = self._require_initialized()
        direction = (
            _sign(destination.x - start.x),
            _sign(destination.y - start.y),
        )
        for raw in _sequence(display.get("方向措辞"), "方向措辞"):
            row = _mapping(raw, "方向措辞")
            if tuple(row.get("方向", ())) == direction:
                return _text(row.get("措辞"), "方向措辞")
        raise TravelError(f"没有方向措辞：{direction}")

    @staticmethod
    def _threshold_word(rows: Any, field: str, value: int) -> str:
        for raw in _sequence(rows, "阈值措辞"):
            row = _mapping(raw, "阈值措辞")
            upper = row.get(field)
            if upper is None or value <= _integer(upper, field):
                return _text(row.get("措辞"), "阈值措辞")
        raise TravelError("阈值措辞没有兜底项")

    def _validate_connectivity(self) -> None:
        locations = tuple(self._graph)
        if not locations:
            raise TravelError("世界没有地点")
        visited = {locations[0]}
        pending = [locations[0]]
        while pending:
            node = pending.pop()
            for road in self._graph[node]:
                if road.destination not in visited:
                    visited.add(road.destination)
                    pending.append(road.destination)
        if visited != set(locations):
            missing = "、".join(sorted(set(locations) - visited))
            raise TravelError(f"世界路网没有全部连通：{missing}")

    def _require_initialized(self) -> Mapping[str, Any]:
        if self._display is None:
            raise RuntimeError("行程微服务尚未初始化")
        return self._display


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TravelError(f"{label} 必须是对象")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TravelError(f"{label} 必须是列表")
    return value


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    result = str(value or "").strip()
    if not result and not allow_empty:
        raise TravelError(f"{label} 不能为空")
    return result


def _positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise TravelError(f"{label} 必须是正数")
    return float(value)


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TravelError(f"{label} 必须是整数")
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _integer(value, label)
    if result < 1:
        raise TravelError(f"{label} 必须大于 0")
    return result


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise TravelError(f"{label} 必须是布尔值")
    return value


def _integer_pair(value: Any, label: str) -> tuple[int, int]:
    values = _sequence(value, label)
    if len(values) != 2:
        raise TravelError(f"{label} 必须包含两个整数")
    return _integer(values[0], label), _integer(values[1], label)


def _strings(value: Any, label: str) -> tuple[str, ...]:
    result = tuple(_text(item, label) for item in _sequence(value, label))
    if len(result) != len(set(result)):
        raise TravelError(f"{label} 不能重复")
    return result


def _strict_fields(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    missing = allowed - set(value)
    if unknown or missing:
        details = []
        if unknown:
            details.append("未知字段 " + "、".join(sorted(unknown)))
        if missing:
            details.append("缺少字段 " + "、".join(sorted(missing)))
        raise TravelError(f"{label}字段不完整：{'；'.join(details)}")


def _sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


__all__ = ["TravelService"]
