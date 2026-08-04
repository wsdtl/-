"""按全地表通行规则自动选择最优行程并生成叙事。"""

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
    TravelEndpoint,
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
        "地形段数": "段",
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
        "经由地形",
        "首段通行",
        "末段通行",
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
class _Step:
    start: SurfaceCoordinate
    destination: SurfaceCoordinate
    kind: str
    name: str
    adjusted: float


class TravelService:
    """消费世界事实和行路 JSON，不保存人物位置。"""

    def __init__(self, data: JsonDataService, world: WorldService) -> None:
        self._data = data
        self._world = world
        self._metrics: tuple[str, ...] = ()
        self._sort_metrics: tuple[str, ...] = ()
        self._road_edges: dict[tuple[SurfaceCoordinate, SurfaceCoordinate], str] = {}
        self._road_count = 0
        self._road_multipliers: dict[str, float] = {}
        self._terrain_multipliers: dict[str, float] = {}
        self._terrain_cache: dict[SurfaceCoordinate, str] = {}
        self._horizontal_weight = 0.0
        self._ascent_weight = 0.0
        self._descent_weight = 0.0
        self._diagonal_multiplier = 0.0
        self._allowed_steps: frozenset[tuple[int, int]] = frozenset()
        self._default_bidirectional = True
        self._road_coordinates_must_be_continuous = True
        self._allow_offroad = True
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
                "地形来源",
                "水平尺度来源",
                "展示来源",
                "坐标规则",
                "路网要求",
                "自动选路",
                "路程折算",
                "行程事实",
                "境界影响",
            },
            "行程规则",
        )
        self._validate_sources(raw_rule)
        self._metrics = self._load_metrics(definitions)
        coordinate_rule = _mapping(raw_rule.get("坐标规则"), "坐标规则")
        _strict_fields(
            coordinate_rule,
            {"维数", "允许相邻步", "斜向距离倍率"},
            "坐标规则",
        )
        if _positive_int(coordinate_rule.get("维数"), "道路坐标维数") != 2:
            raise TravelError("道路坐标维数必须是 2")
        self._default_bidirectional = _boolean(
            _mapping(raw_rule.get("路网要求"), "路网要求").get("道路默认双向"),
            "道路默认双向",
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
            self._data.dataset("道路通行规则")
        )
        if set(self._road_multipliers) != set(self._world.world().road_types):
            raise TravelError("道路折算倍率与世界道路不一致")
        self._terrain_multipliers = self._load_terrain_multipliers(
            self._data.dataset("地形通行规则")
        )
        expected_terrains = {
            partition.terrain
            for region in self._world.regions()
            for partition in region.terrain_partitions
        }
        if set(self._terrain_multipliers) != expected_terrains:
            raise TravelError("地形通行倍率与区域地形分区不一致")
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
        self._road_edges = self._build_road_edges(self._world.roads())
        self._road_count = len(self._world.roads())
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
        start = self._resolve_endpoint(request.start)
        destination = self._resolve_endpoint(request.destination)
        if start.coordinate == destination.coordinate:
            raise TravelError("行程起点与终点不能相同")
        steps = self._find_route(start.coordinate, destination.coordinate)
        points = self._route_points(steps)
        metrics = self._metrics_for(steps, points)
        via_locations = self._via_locations(
            points, start.coordinate, destination.coordinate
        )
        road_types = self._run_names(steps, "道路")
        terrain_types = self._run_names(steps, "地形")
        turning_coordinate = self._turning_coordinate(steps)
        turning = self._turning_label(turning_coordinate)
        narrative = self._narrative(
            start=start.label,
            destination=destination.label,
            via_locations=via_locations,
            steps=steps,
            turning=turning,
            metrics=metrics,
        )
        return TravelPlan(
            start=start.label,
            destination=destination.label,
            destination_region=self._world.region_at(destination.coordinate).identity,
            via_locations=via_locations,
            road_types=road_types,
            terrain_types=terrain_types,
            terrain_turning_location=turning,
            terrain_turning_coordinate=turning_coordinate,
            points=points,
            metrics=metrics,
            narrative=narrative,
        )

    def _build_road_edges(
        self,
        roads: tuple[RoadDefinition, ...],
    ) -> dict[tuple[SurfaceCoordinate, SurfaceCoordinate], str]:
        edges: dict[tuple[SurfaceCoordinate, SurfaceCoordinate], str] = {}
        for road in roads:
            coordinates = self._validated_coordinates(road)
            for left, right in itertools.pairwise(coordinates):
                self._register_road_edge(edges, left, right, road.road_type)
                if self._default_bidirectional:
                    self._register_road_edge(edges, right, left, road.road_type)
        return edges

    def _register_road_edge(
        self,
        edges: dict[tuple[SurfaceCoordinate, SurfaceCoordinate], str],
        start: SurfaceCoordinate,
        destination: SurfaceCoordinate,
        road_type: str,
    ) -> None:
        key = (start, destination)
        previous = edges.get(key)
        if (
            previous is None
            or self._road_multipliers[road_type] < self._road_multipliers[previous]
        ):
            edges[key] = road_type

    def _validated_coordinates(
        self,
        road: RoadDefinition,
    ) -> tuple[SurfaceCoordinate, ...]:
        coordinates = list(road.coordinates)
        start = self._world.location(road.start).coordinate
        destination = self._world.location(road.destination).coordinate
        if coordinates[0] != start:
            raise TravelError(f"道路起点坐标不一致：{road.start}")
        if coordinates[-1] != destination:
            raise TravelError(f"道路终点坐标不一致：{road.destination}")
        if len(coordinates) != len(set(coordinates)):
            raise TravelError(f"道路存在重复坐标：{road.start} -> {road.destination}")
        for left, right in itertools.pairwise(coordinates):
            step = (right.x - left.x, right.y - left.y)
            if step not in self._allowed_steps:
                raise TravelError(
                    f"道路坐标使用未允许步长 {step}：{road.start} -> {road.destination}"
                )
        return tuple(coordinates)

    def _find_route(
        self,
        start: SurfaceCoordinate,
        destination: SurfaceCoordinate,
    ) -> tuple[_Step, ...]:
        serial = itertools.count()
        zero = self._route_sort_key(0.0, 0, 0.0)
        initial_state = (start, "", "")
        queue: list[
            tuple[
                tuple[float, ...],
                int,
                tuple[SurfaceCoordinate, str, str],
                tuple[float, ...],
                float,
                int,
                float,
            ]
        ] = [
            (
                self._priority(zero, start, destination),
                next(serial),
                initial_state,
                zero,
                0.0,
                0,
                0.0,
            )
        ]
        best: dict[tuple[SurfaceCoordinate, str, str], tuple[float, ...]] = {
            initial_state: zero
        }
        previous: dict[
            tuple[SurfaceCoordinate, str, str],
            tuple[tuple[SurfaceCoordinate, str, str], _Step],
        ] = {}
        goal_states: dict[tuple[SurfaceCoordinate, str, str], tuple[float, ...]] = {}
        goal_adjusted = math.inf
        while queue:
            _, _, state, cost, adjusted, road_segments, horizontal = heapq.heappop(
                queue
            )
            if cost != best.get(state):
                continue
            node, previous_kind, previous_name = state
            if node == destination:
                goal_states[state] = cost
                goal_adjusted = min(goal_adjusted, adjusted)
                continue
            if (
                goal_adjusted < math.inf
                and adjusted + self._heuristic(node, destination) > goal_adjusted
            ):
                continue
            for neighbor in self._neighbors(node):
                step = self._step(node, neighbor)
                next_adjusted = adjusted + step.adjusted
                next_segments = road_segments + int(
                    step.kind == "道路"
                    and (previous_kind != "道路" or previous_name != step.name)
                )
                next_horizontal = horizontal + self._horizontal_distance(node, neighbor)
                next_cost = self._route_sort_key(
                    next_adjusted,
                    next_segments,
                    next_horizontal,
                )
                next_state = (neighbor, step.kind, step.name)
                if next_cost >= best.get(
                    next_state, tuple(math.inf for _ in self._sort_metrics)
                ):
                    continue
                best[next_state] = next_cost
                previous[next_state] = (state, step)
                heapq.heappush(
                    queue,
                    (
                        self._priority(next_cost, neighbor, destination),
                        next(serial),
                        next_state,
                        next_cost,
                        next_adjusted,
                        next_segments,
                        next_horizontal,
                    ),
                )
        if not goal_states:
            raise TravelError(
                f"地表没有可行路线：({start.x}, {start.y}) -> ({destination.x}, {destination.y})"
            )
        goal_state = min(goal_states, key=lambda state: goal_states[state])
        route: list[_Step] = []
        state = goal_state
        while state != initial_state:
            state, step = previous[state]
            route.append(step)
        route.reverse()
        return tuple(route)

    def _priority(
        self,
        cost: tuple[float, ...],
        coordinate: SurfaceCoordinate,
        destination: SurfaceCoordinate,
    ) -> tuple[float, ...]:
        values = list(cost)
        if values:
            values[0] += self._heuristic(coordinate, destination)
        return tuple(values)

    def _heuristic(
        self, coordinate: SurfaceCoordinate, destination: SurfaceCoordinate
    ) -> float:
        dx = abs(destination.x - coordinate.x)
        dy = abs(destination.y - coordinate.y)
        horizontal_steps = max(dx, dy) + (self._diagonal_multiplier - 1) * min(dx, dy)
        minimum_multiplier = min(
            (*self._road_multipliers.values(), *self._terrain_multipliers.values())
        )
        return (
            horizontal_steps
            * self._world.world().meters_per_grid
            * self._horizontal_weight
            * minimum_multiplier
        )

    def _neighbors(
        self, coordinate: SurfaceCoordinate
    ) -> tuple[SurfaceCoordinate, ...]:
        result = []
        bounds = self._world.world().bounds
        for dx, dy in self._allowed_steps:
            neighbor = SurfaceCoordinate(coordinate.x + dx, coordinate.y + dy)
            if bounds.contains(neighbor):
                result.append(neighbor)
        return tuple(result)

    def _step(self, start: SurfaceCoordinate, destination: SurfaceCoordinate) -> _Step:
        road_type = self._road_edges.get((start, destination))
        if road_type is not None:
            name = road_type
            kind = "道路"
            multiplier = self._road_multipliers[road_type]
        else:
            left = self._terrain(start)
            right = self._terrain(destination)
            name = left if left == right else f"{left}与{right}交界"
            kind = "地形"
            multiplier = (
                self._terrain_multipliers[left] + self._terrain_multipliers[right]
            ) / 2
        horizontal = self._horizontal_distance(start, destination)
        difference = self._world.altitude(destination) - self._world.altitude(start)
        ascent = max(difference, 0)
        descent = max(-difference, 0)
        adjusted = multiplier * (
            horizontal * self._horizontal_weight
            + ascent * self._ascent_weight
            + descent * self._descent_weight
        )
        return _Step(start, destination, kind, name, adjusted)

    def _terrain(self, coordinate: SurfaceCoordinate) -> str:
        terrain = self._terrain_cache.get(coordinate)
        if terrain is None:
            terrain = self._world.terrain_at(coordinate)
            self._terrain_cache[coordinate] = terrain
        return terrain

    def _horizontal_distance(
        self, start: SurfaceCoordinate, destination: SurfaceCoordinate
    ) -> float:
        diagonal = start.x != destination.x and start.y != destination.y
        return self._world.world().meters_per_grid * (
            self._diagonal_multiplier if diagonal else 1.0
        )

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

    def _route_points(self, steps: tuple[_Step, ...]) -> tuple[SurfacePoint, ...]:
        coordinates = [steps[0].start]
        coordinates.extend(step.destination for step in steps)
        return tuple(self._world.surface_point(value) for value in coordinates)

    def _metrics_for(
        self,
        steps: tuple[_Step, ...],
        points: tuple[SurfacePoint, ...],
    ) -> TravelMetrics:
        horizontal = sum(
            self._horizontal_distance(step.start, step.destination) for step in steps
        )
        ascent = 0
        descent = 0
        adjusted = sum(step.adjusted for step in steps)
        road_segments = 0
        terrain_segments = 0
        previous: tuple[str, str] | None = None
        for step in steps:
            current = (step.kind, step.name)
            if current != previous:
                if step.kind == "道路":
                    road_segments += 1
                else:
                    terrain_segments += 1
            previous = current
            difference = self._world.altitude(step.destination) - self._world.altitude(
                step.start
            )
            ascent += max(difference, 0)
            descent += max(-difference, 0)
        step_up = 0
        step_down = 0
        uphill = 0.0
        downhill = 0.0
        scale = self._world.world().meters_per_grid
        for left, right in itertools.pairwise(points):
            difference = right.altitude - left.altitude
            dx = abs(right.coordinate.x - left.coordinate.x)
            dy = abs(right.coordinate.y - left.coordinate.y)
            step_distance = scale * (self._diagonal_multiplier if dx and dy else 1.0)
            if difference > 0:
                step_up = max(step_up, difference)
                uphill = max(uphill, difference / step_distance * 1000)
            else:
                step_down = max(step_down, -difference)
                downhill = max(downhill, -difference / step_distance * 1000)
        altitudes = tuple(point.altitude for point in points)
        return TravelMetrics(
            horizontal_distance=round(horizontal),
            road_segments=road_segments,
            terrain_segments=terrain_segments,
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

    def _via_locations(
        self,
        points: tuple[SurfacePoint, ...],
        start: SurfaceCoordinate,
        destination: SurfaceCoordinate,
    ) -> tuple[str, ...]:
        by_coordinate = {
            location.coordinate: location.identity
            for location in self._world.locations()
        }
        return tuple(
            by_coordinate[point.coordinate]
            for point in points[1:-1]
            if point.coordinate in by_coordinate
            and point.coordinate not in {start, destination}
        )

    @staticmethod
    def _run_names(steps: tuple[_Step, ...], kind: str) -> tuple[str, ...]:
        result = []
        for step in steps:
            if step.kind == kind and (not result or result[-1] != step.name):
                result.append(step.name)
        return tuple(result)

    def _turning_coordinate(self, steps: tuple[_Step, ...]) -> SurfaceCoordinate | None:
        candidates = []
        for step in steps:
            difference = self._world.altitude(step.destination) - self._world.altitude(
                step.start
            )
            if difference > 0:
                candidates.append((difference, step.destination))
        return max(candidates, default=(0, None), key=lambda value: value[0])[1]

    def _turning_label(self, coordinate: SurfaceCoordinate | None) -> str:
        if coordinate is None:
            return ""
        for location in self._world.locations():
            if location.coordinate == coordinate:
                return location.identity
        return f"({coordinate.x}, {coordinate.y})"

    def _narrative(
        self,
        *,
        start: str,
        destination: str,
        via_locations: tuple[str, ...],
        steps: tuple[_Step, ...],
        turning: str,
        metrics: TravelMetrics,
    ) -> str:
        display = self._require_initialized()
        narrative = _mapping(display.get("叙事"), "行程叙事")
        first = steps[0]
        direction = self._direction_word(first.start, first.destination)
        first_words = self._passage_words(first)
        start_text = _text(narrative.get("起程"), "起程模板").format(
            起点=start,
            首段通行措辞=_text(first_words.get("起行"), "起行措辞").format(
                方向=direction,
                地形=first.name,
            ),
        )
        transitions = []
        for previous, current in itertools.pairwise(steps):
            if (current.kind, current.name) == (previous.kind, previous.name):
                continue
            current_words = self._passage_words(current)
            transitions.append(
                _text(current_words.get("转入"), "通行转入措辞").format(
                    地形=current.name
                )
            )
        via_text = ""
        if via_locations:
            transition_text = ""
            if transitions:
                transition_text = "，" + "，再".join(transitions)
            via_text = _text(narrative.get("经由"), "经由模板").format(
                经由地点="、".join(via_locations),
                转入通行措辞=transition_text,
            )
        elif transitions:
            via_text = _text(
                narrative.get("没有经由地点", ""), "无地点模板", allow_empty=True
            ).format(转入通行措辞="，".join(transitions))
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
        last_words = self._passage_words(steps[-1])
        destination_text = _text(narrative.get("抵达"), "抵达模板").format(
            末段通行措辞=_text(last_words.get("收束"), "通行收束措辞").format(
                地形=steps[-1].name
            ),
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
            or _text(
                narrative.get("没有经由地点", ""), "没有经由地点模板", allow_empty=True
            ).format(转入通行措辞=", ".join(transitions)),
            "地势": terrain_text,
            "抵达": destination_text,
            "总览": overview,
        }
        return "\n".join(
            sections[name] for name in self._narrative_order if sections[name]
        )

    def _passage_words(self, step: _Step) -> Mapping[str, Any]:
        display = self._require_initialized()
        if step.kind == "道路":
            rows = {
                _text(row.get("道路"), "道路措辞名称"): row
                for row in (
                    _mapping(value, "道路措辞")
                    for value in _sequence(display.get("道路措辞"), "道路措辞")
                )
            }
            return _mapping(rows.get(step.name), f"道路措辞 {step.name}")
        return _mapping(display.get("地形措辞"), "地形措辞")

    def _resolve_endpoint(self, reference: Any) -> TravelEndpoint:
        if isinstance(reference, TravelEndpoint):
            label = _text(reference.label, "行路端点名称")
            self._world.surface_point(reference.coordinate)
            return TravelEndpoint(label=label, coordinate=reference.coordinate)
        if isinstance(reference, str):
            location = self._world.location(reference)
            return TravelEndpoint(location.identity, location.coordinate)
        coordinate = _coordinate(reference, "行路端点坐标")
        self._world.surface_point(coordinate)
        for location in self._world.locations():
            if location.coordinate == coordinate:
                return TravelEndpoint(location.identity, coordinate)
        return TravelEndpoint(f"({coordinate.x}, {coordinate.y})", coordinate)

    def _validate_sources(self, rule: Mapping[str, Any]) -> None:
        world = self._world.world()
        expected = {
            "道路来源": f"{world.identity}.道路",
            "地势来源": "地势.地表高度",
            "地形来源": "区域.地形分区",
            "水平尺度来源": "地势.水平每格米数",
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
            _integer_pair(raw, "允许相邻步") for raw in _sequence(value, "允许相邻步")
        )
        if not steps or (0, 0) in steps:
            raise TravelError("允许相邻步不能为空且不能包含原地停留")
        return steps

    @staticmethod
    def _load_road_multipliers(value: Any) -> dict[str, float]:
        result: dict[str, float] = {}
        for raw in _dataset_rows(value, "道路通行规则"):
            row = _mapping(raw, "道路通行倍率")
            _strict_fields(row, {"道路", "倍率"}, "道路倍率")
            name = _text(row.get("道路"), "道路倍率名称")
            if name in result:
                raise TravelError(f"道路倍率重复：{name}")
            result[name] = _positive_number(row.get("倍率"), "道路倍率")
        return result

    @staticmethod
    def _load_terrain_multipliers(value: Any) -> dict[str, float]:
        result: dict[str, float] = {}
        for raw in _dataset_rows(value, "地形通行规则"):
            row = _mapping(raw, "地形通行倍率")
            _strict_fields(row, {"地形", "倍率"}, "地形倍率")
            name = _text(row.get("地形"), "地形倍率名称")
            if name in result:
                raise TravelError(f"地形倍率重复：{name}")
            result[name] = _positive_number(row.get("倍率"), "地形倍率")
        return result

    def _load_network_rules(self, rule: Mapping[str, Any]) -> None:
        network = _mapping(rule.get("路网要求"), "路网要求")
        _strict_fields(
            network,
            {"道路坐标必须连续", "道路默认双向", "道路之外允许行走"},
            "路网要求",
        )
        self._road_coordinates_must_be_continuous = _boolean(
            network.get("道路坐标必须连续"), "道路坐标必须连续"
        )
        self._allow_offroad = _boolean(
            network.get("道路之外允许行走"), "道路之外允许行走"
        )
        if not self._allow_offroad:
            raise TravelError("当前全地表行路契约必须允许道路之外行走")

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
            {
                "距离",
                "方向措辞",
                "道路措辞",
                "地形措辞",
                "爬升措辞",
                "海拔措辞",
                "叙事",
            },
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


def _dataset_rows(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, Mapping):
        if len(value) != 1:
            raise TravelError(f"{label}必须只包含一个文件列表")
        value = next(iter(value.values()))
    return _sequence(value, label)


def _coordinate(value: Any, label: str) -> SurfaceCoordinate:
    if isinstance(value, SurfaceCoordinate):
        return value
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != 2
    ):
        raise TravelError(f"{label}必须是包含两个整数的坐标")
    values = tuple(value)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in values):
        raise TravelError(f"{label}必须是包含两个整数的坐标")
    return SurfaceCoordinate(x=values[0], y=values[1])


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
