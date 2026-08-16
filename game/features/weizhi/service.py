"""当前位置、本地修士和附近对象的玩法编排。"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

from game.core.character import CharacterService
from game.core.companion import CompanionService, LocalCultivator
from game.core.data import JsonDataError, JsonDataService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    CurrentPositionView,
    NearbyCultivatorPage,
    NearbyCultivatorView,
    NearbyOverview,
    NearbyPageError,
    NearbyWorldLocation,
    NearbyWorldLocations,
    PositionAction,
    PositionCopy,
)
from .presentation import ButtonTemplate, load_position_presentation, render_action


class PositionFeature:
    """组合位置、世界、人物公开摘要、状态和本地修士。"""

    def __init__(
        self,
        data: JsonDataService,
        world: WorldService,
        location: LocationService,
        character: CharacterService,
        player_state: PlayerStateService,
        companion: CompanionService,
    ) -> None:
        self._data = data
        self._world = world
        self._location = location
        self._character = character
        self._player_state = player_state
        self._companion = companion
        self._initialized = False
        self._location_radius_meters = 0
        self._location_limit = 0
        self._meters_per_li = 0
        self._rounding_step = 0
        self._same_place = ""
        self._open_functions: frozenset[str] = frozenset()
        self._directions: Mapping[tuple[int, int], str] = {}
        self._copy: PositionCopy | None = None
        self._buttons: tuple[ButtonTemplate, ...] = ()

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("位置查看玩法微服务已经初始化")
        for initialized, label in (
            (self._world.status().initialized, "世界核心"),
            (self._location.status().initialized, "玩家位置核心"),
            (self._character.status().initialized, "角色核心"),
            (self._player_state.status().initialized, "人物状态核心"),
            (self._companion.status().initialized, "世界道侣核心"),
        ):
            if not initialized:
                raise RuntimeError(f"{label}必须先于位置查看玩法启动")
        nearby = self._data.dataset("位置规则").get("附近")
        nearby_rule = _mapping(nearby, "附近.json")
        location_rule = _mapping(nearby_rule.get("地点"), "附近.地点")
        self._location_radius_meters = _positive_int(
            location_rule.get("范围米数"), "附近.地点.范围米数"
        )
        self._location_limit = _positive_int(
            location_rule.get("最多数量"), "附近.地点.最多数量"
        )
        presentation = load_position_presentation(self._data.dataset("位置展示"))
        self._meters_per_li = presentation.meters_per_li
        self._rounding_step = presentation.rounding_step
        self._same_place = presentation.same_place
        self._open_functions = presentation.open_functions
        self._directions = presentation.directions
        self._copy = presentation.copy
        self._buttons = presentation.buttons
        self._initialized = True

    def copy(self) -> PositionCopy:
        self._require_initialized()
        if self._copy is None:
            raise RuntimeError("位置展示文案尚未初始化")
        return self._copy

    def position_actions(self) -> tuple[PositionAction, ...]:
        self._require_initialized()
        return self._actions_for("位置")

    def nearby_overview_actions(
        self, locations: Sequence[NearbyWorldLocation] = ()
    ) -> tuple[PositionAction, ...]:
        self._require_initialized()
        return self._location_entry_actions(locations) + self._actions_for("概览")

    def nearby_cultivator_actions(
        self, page: int, has_next: bool
    ) -> tuple[PositionAction, ...]:
        self._require_initialized()
        result: list[PositionAction] = []
        for template in self._buttons:
            if template.page != "修士":
                continue
            if template.condition == "有上一页":
                if page <= 1:
                    continue
                variables = {"页码": page - 1}
            elif template.condition == "有下一页":
                if not has_next:
                    continue
                variables = {"页码": page + 1}
            else:
                variables = {}
            result.append(render_action(template, variables))
        return tuple(result)

    def nearby_location_actions(
        self, locations: Sequence[NearbyWorldLocation]
    ) -> tuple[PositionAction, ...]:
        self._require_initialized()
        result = list(self._location_entry_actions(locations))
        result.extend(self._actions_for("地点"))
        return tuple(result)

    async def current(self, user_id: str) -> CurrentPositionView:
        self._require_initialized()
        current, active = await asyncio.gather(
            self._location.current(user_id),
            self._companion.active(user_id),
        )
        location = self._visible_location(
            self._world.locate(LocationQuery(xy=current.xy))
        )
        excluded = (active.companion_id,) if active is not None else ()
        local = (
            self._companion.local_cultivators(
                location.location_name,
                exclude_companion_ids=excluded,
            )
            if location.companion_pool
            else ()
        )
        return CurrentPositionView(
            location,
            local,
            self._active_summary(active.companion_id) if active is not None else None,
        )

    async def nearby_overview(self, user_id: str) -> NearbyOverview:
        self._require_initialized()
        current, cultivators, locations = await asyncio.gather(
            self.current(user_id),
            self.nearby_cultivators(user_id),
            self.nearby_locations(user_id),
        )
        return NearbyOverview(
            current=current,
            visiting_cultivator_count=cultivators.visible_count,
            locations=locations.values,
        )

    async def nearby_cultivators(
        self, user_id: str, page: int = 1
    ) -> NearbyCultivatorPage:
        self._require_initialized()
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise NearbyPageError(self.copy().invalid_page)
        candidates, active = await asyncio.gather(
            self._location.nearby_players(user_id),
            self._companion.active(user_id),
        )
        user_ids = tuple(value.user_id for value in candidates.values)
        profiles, states = await asyncio.gather(
            self._character.public_profiles(user_ids),
            self._player_state.public_many(user_ids),
        )
        profile_by_user = {value.user_id: value for value in profiles}
        state_by_user = {value.user_id: value for value in states}
        visible: list[NearbyCultivatorView] = []
        for candidate in candidates.values:
            profile = profile_by_user.get(candidate.user_id)
            state = state_by_user.get(candidate.user_id)
            if profile is None or state is None or not state.appears_nearby:
                continue
            visible.append(
                NearbyCultivatorView(
                    user_id=candidate.user_id,
                    name=profile.name,
                    gender=profile.gender,
                    realm_name=profile.realm_name,
                    level=profile.level,
                    states=state.names,
                    direction=self._direction(candidates.origin.xy, candidate.xy),
                    distance=self._distance(candidate.distance_squared_meters),
                )
            )
        truncated = candidates.candidate_limit_reached or (
            len(visible) > candidates.visible_limit
        )
        visible = visible[: candidates.visible_limit]
        start = (page - 1) * candidates.page_size
        if page > 1 and start >= len(visible):
            raise NearbyPageError(self.copy().missing_page)
        stop = start + candidates.page_size
        current = self._world.locate(LocationQuery(xy=candidates.origin.xy))
        local = (
            self._companion.local_cultivators(
                current.location_name,
                exclude_companion_ids=(active.companion_id,) if active else (),
            )
            if page == 1 and current.companion_pool
            else ()
        )
        return NearbyCultivatorPage(
            local_cultivators=local,
            active_companion=(
                self._active_summary(active.companion_id)
                if active is not None and page == 1
                else None
            ),
            cultivators=tuple(visible[start:stop]),
            page=page,
            page_size=candidates.page_size,
            has_next=stop < len(visible),
            truncated=truncated,
            visible_count=len(visible),
        )

    def _active_summary(self, companion_id: str) -> LocalCultivator:
        definition = self._companion.definition(companion_id)
        return LocalCultivator(
            definition.companion_id,
            definition.name,
            definition.gender,
            definition.title,
            definition.description,
            definition.realm_id,
            definition.realm_name,
            definition.level,
            definition.interactable,
        )

    async def nearby_locations(self, user_id: str) -> NearbyWorldLocations:
        self._require_initialized()
        current = await self._location.current(user_id)
        map_view = self._world.map_view()
        origin_altitude = self._world.locate(LocationQuery(xy=current.xy)).altitude
        radius_squared = self._location_radius_meters**2
        values: list[tuple[int, object]] = []
        for location in map_view.locations:
            if location.xy == current.xy:
                continue
            dx = location.xy[0] - current.xy[0]
            dy = location.xy[1] - current.xy[1]
            horizontal_squared = (dx * dx + dy * dy) * map_view.cell_size_meters**2
            distance_squared = (
                horizontal_squared + (location.altitude - origin_altitude) ** 2
            )
            if distance_squared <= radius_squared:
                values.append((distance_squared, location))
        values.sort(key=lambda entry: (entry[0], entry[1].xy, entry[1].name))
        return NearbyWorldLocations(
            tuple(
                NearbyWorldLocation(
                    name=location.name,
                    region=location.region,
                    terrain=location.terrain,
                    functions=self._visible_functions(location.available_functions),
                    direction=self._direction(current.xy, location.xy),
                    distance=self._distance(distance_squared),
                )
                for distance_squared, location in values[: self._location_limit]
            )
        )

    def _direction(self, origin: tuple[int, int], target: tuple[int, int]) -> str:
        offset = (_sign(target[0] - origin[0]), _sign(target[1] - origin[1]))
        if offset == (0, 0):
            return ""
        return self._directions[offset]

    def _distance(self, distance_squared_meters: int) -> str:
        if distance_squared_meters == 0:
            return self._same_place
        distance_meters = math.sqrt(distance_squared_meters)
        distance_li = distance_meters / self._meters_per_li
        rounded = max(
            self._rounding_step,
            int(distance_li / self._rounding_step + 0.5) * self._rounding_step,
        )
        return f"约{rounded}里"

    def _visible_location(self, location):
        return replace(
            location,
            available_functions=self._visible_functions(location.available_functions),
        )

    def _visible_functions(self, functions: Sequence[str]) -> tuple[str, ...]:
        return tuple(value for value in functions if value in self._open_functions)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("位置查看玩法微服务尚未初始化")

    def _actions_for(self, page: str) -> tuple[PositionAction, ...]:
        return tuple(
            render_action(template, {})
            for template in self._buttons
            if template.page == page and not template.condition
        )

    def _location_entry_actions(
        self, locations: Sequence[NearbyWorldLocation]
    ) -> tuple[PositionAction, ...]:
        result: list[PositionAction] = []
        entry_templates = tuple(
            template for template in self._buttons if template.page == "地点条目"
        )
        for index, location in enumerate(locations, start=1):
            for template in entry_templates:
                action = render_action(template, {"地点": location.name})
                result.append(
                    PositionAction(
                        action_id=f"{action.action_id}.{index}",
                        label=action.label,
                        command=action.command,
                        behavior=action.behavior,
                        style=action.style,
                    )
                )
        return tuple(result)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


__all__ = ["PositionFeature"]
