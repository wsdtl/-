"""位置命令回复构造。"""

from __future__ import annotations

from game.features.weizhi import (
    CurrentPositionView,
    NearbyCultivatorPage,
    NearbyOverview,
    NearbyWorldLocation,
    NearbyWorldLocations,
    PositionAction,
    PositionCopy,
)
from message import Action, M


def current(
    copy: PositionCopy, result: CurrentPositionView, actions: tuple[PositionAction, ...]
):
    location = result.location
    builder = (
        M.document()
        .header(_location_name(copy, location))
        .section(copy.current_place_section, icon=copy.location_icon)
        .row(
            (copy.region_label, location.region), (copy.terrain_label, location.terrain)
        )
        .row(
            (copy.coordinate_label, _coordinate(copy, location.xy)),
            (copy.altitude_label, copy.altitude.format(海拔=location.altitude)),
        )
        .section(copy.available_functions_section, icon=copy.function_icon)
    )
    if location.available_functions:
        for index, name in enumerate(location.available_functions, start=1):
            builder.item(index, name)
    else:
        builder.line(copy.no_available_functions)
    if result.local_cultivators:
        builder.section(
            copy.local_cultivators_section, icon=copy.cultivator_icon
        ).field(copy.count_label, len(result.local_cultivators))
    if result.active_companion is not None:
        builder.section(copy.active_companion_section, icon=copy.cultivator_icon).field(
            result.active_companion.name, result.active_companion.title
        )
    return builder.actions(_actions(actions)).build()


def nearby_overview(
    copy: PositionCopy, result: NearbyOverview, actions: tuple[PositionAction, ...]
):
    location = result.current.location
    location_name = _location_name(copy, location)
    builder = (
        M.document()
        .header(copy.overview_title.format(地点=location_name))
        .section(copy.overview_cultivators_section, icon=copy.cultivator_icon)
        .row(
            (copy.overview_local_label, len(result.current.local_cultivators)),
            (copy.overview_visiting_label, result.visiting_cultivator_count),
        )
        .section(copy.overview_locations_section, icon=copy.location_icon)
    )
    if result.locations:
        for index, nearby in enumerate(result.locations, start=1):
            _append_location(builder, copy, index, nearby)
    else:
        builder.line(copy.overview_no_locations)
    builder.section(copy.overview_current_section, icon=copy.navigation_icon)
    builder.field(copy.overview_current_label, location_name)
    builder.row(
        (copy.region_label, location.region), (copy.terrain_label, location.terrain)
    )
    return builder.actions(_actions(actions)).build()


def nearby_cultivators(
    copy: PositionCopy,
    result: NearbyCultivatorPage,
    actions: tuple[PositionAction, ...],
):
    builder = M.document().header(copy.cultivators_title)
    if result.active_companion is not None:
        builder.section(
            copy.cultivators_active_section, icon=copy.cultivator_icon
        ).field(
            result.active_companion.name,
            copy.cultivator_summary.format(
                境界=result.active_companion.realm_name,
                等级=result.active_companion.level,
                性别=result.active_companion.gender,
                状态="",
            ),
        )
    if result.local_cultivators:
        builder.section(copy.cultivators_local_section, icon=copy.cultivator_icon)
        for local in result.local_cultivators:
            builder.field(
                local.name,
                copy.cultivator_summary.format(
                    境界=local.realm_name, 等级=local.level, 性别=local.gender, 状态=""
                ),
            ).line(local.description)
    builder.section(copy.cultivators_visiting_section, icon=copy.navigation_icon)
    if result.cultivators:
        for cultivator in result.cultivators:
            state = copy.state_separator.join(cultivator.states)
            state_text = copy.state_prefix.format(状态=state) if state else ""
            builder.field(
                cultivator.name,
                copy.cultivator_summary.format(
                    境界=cultivator.realm_name,
                    等级=cultivator.level,
                    性别=cultivator.gender,
                    状态=state_text,
                ),
            ).line(
                copy.cultivator_direction.format(
                    方向=cultivator.direction, 距离=cultivator.distance
                )
                if cultivator.direction
                else copy.colocated_cultivator_direction.format(
                    距离=cultivator.distance
                )
            )
    else:
        builder.line(copy.cultivators_empty)
    builder.section(copy.cultivators_page_section, icon=copy.page_icon).field(
        copy.cultivators_current_label, result.page
    )
    if result.truncated:
        builder.line(copy.cultivators_truncated)
    return builder.actions(_actions(actions)).build()


def nearby_locations(
    copy: PositionCopy,
    result: NearbyWorldLocations,
    actions: tuple[PositionAction, ...],
):
    builder = (
        M.document()
        .header(copy.locations_title)
        .section(copy.locations_section, icon=copy.location_icon)
    )
    if not result.values:
        builder.line(copy.locations_empty)
    for index, location in enumerate(result.values, start=1):
        _append_location(builder, copy, index, location)
    return builder.actions(_actions(actions)).build()


def error(
    copy: PositionCopy, title: str, message: str, actions: tuple[PositionAction, ...]
):
    return (
        M.document()
        .section(title, icon=copy.error_icon)
        .line(message)
        .actions(_actions(actions))
        .build()
    )


def _append_location(
    builder, copy: PositionCopy, index: int, location: NearbyWorldLocation
) -> None:
    functions = (
        copy.function_separator.join(location.functions) or copy.no_available_function
    )
    builder.item(
        index,
        copy.location_summary.format(
            名称=location.name, 方向=location.direction, 距离=location.distance
        ),
    ).line(
        copy.location_detail.format(
            区域=location.region, 地形=location.terrain, 功能=functions
        )
    )


def _location_name(copy: PositionCopy, location) -> str:
    if location.location_name:
        return location.location_name
    return copy.unknown_location.format(区域=location.region, 地形=location.terrain)


def _coordinate(copy: PositionCopy, xy: tuple[int, int]) -> str:
    return copy.coordinate.format(横坐标=xy[0], 纵坐标=xy[1])


def _actions(values: tuple[PositionAction, ...]) -> tuple[Action, ...]:
    return tuple(
        Action(
            value.action_id,
            value.label,
            value.command,
            behavior=value.behavior,
            style=value.style,
        )
        for value in values
    )


__all__ = [
    "current",
    "error",
    "nearby_cultivators",
    "nearby_locations",
    "nearby_overview",
]
