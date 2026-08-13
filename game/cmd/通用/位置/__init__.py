"""位置与附近对象二级组件命令。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.weizhi import (
    CurrentPositionView,
    NearbyCultivatorPage,
    NearbyOverview,
    NearbyPageError,
    NearbyWorldLocation,
    NearbyWorldLocations,
    PositionAction,
    PositionCopy,
    PositionFeature,
)
from message import Action, M

from ...command import GameCommand, HelpSpec


@GameCommand.fullmatch(
    scope="通用",
    cmd="位置",
    guard_rule="已创建",
    help=HelpSpec(
        category="世界",
        summary="查看当前地点、地势与此地开放功能",
        usage=("位置",),
        side_effect="只读查询，不改变人物状态",
        order=20,
    ),
)
async def show_position(*, user_id: str, manager, **_) -> None:
    feature = current_game_services().features.weizhi
    result = await feature.current(user_id)
    await manager.send(_position_message(feature, result))


@GameCommand.command(
    scope="通用",
    cmd="附近",
    guard_rule="自主空闲或休息",
    help=HelpSpec(
        category="世界",
        summary="查看附近地点或修士",
        usage=("附近", "附近 地点", "附近 修士", "附近 修士 页码"),
        side_effect="只读查询，不改变人物状态",
        order=30,
    ),
)
async def show_nearby(*, user_id: str, message: str, manager, **_) -> None:
    feature = current_game_services().features.weizhi
    copy = feature.copy()
    parts = str(message or "").split()
    if not parts:
        await manager.send(
            _nearby_overview_message(feature, await feature.nearby_overview(user_id))
        )
        return
    if parts == ["地点"]:
        await manager.send(
            _nearby_locations_message(feature, await feature.nearby_locations(user_id))
        )
        return
    if parts and parts[0] == "修士" and len(parts) <= 2:
        try:
            if len(parts) == 2:
                try:
                    page = int(parts[1])
                except ValueError as exc:
                    raise NearbyPageError(copy.invalid_page) from exc
            else:
                page = 1
            result = await feature.nearby_cultivators(user_id, page)
            await manager.send(_nearby_cultivators_message(feature, result))
        except NearbyPageError as exc:
            await manager.send(
                M.document()
                .section(copy.cultivators_title, icon=copy.error_icon)
                .line(str(exc))
                .actions(_message_actions(feature.nearby_overview_actions()))
                .build()
            )
        return
    await manager.send(
        M.document()
        .section(copy.overview_title.format(地点="附近"), icon=copy.error_icon)
        .line(copy.invalid_command)
        .actions(_message_actions(feature.nearby_overview_actions()))
        .build()
    )


def _position_message(feature: PositionFeature, result: CurrentPositionView):
    copy = feature.copy()
    location = result.location
    reply = (
        M.document()
        .header(_location_name(copy, location))
        .section(copy.current_place_section, icon=copy.location_icon)
        .row(
            (copy.region_label, location.region),
            (copy.terrain_label, location.terrain),
        )
        .row(
            (copy.coordinate_label, _coordinate(copy, location.xy)),
            (copy.altitude_label, copy.altitude.format(海拔=location.altitude)),
        )
        .section(copy.available_functions_section, icon=copy.function_icon)
    )
    if location.available_functions:
        for index, name in enumerate(location.available_functions, start=1):
            reply.item(index, name)
    else:
        reply.line(copy.no_available_functions)
    if result.local_cultivators:
        reply.section(copy.local_cultivators_section, icon=copy.cultivator_icon).field(
            copy.count_label, len(result.local_cultivators)
        )
    if result.active_companion is not None:
        reply.section(copy.active_companion_section, icon=copy.cultivator_icon).field(
            result.active_companion.name,
            result.active_companion.title,
        )
    return reply.actions(_message_actions(feature.position_actions())).build()


def _nearby_overview_message(feature: PositionFeature, result: NearbyOverview):
    copy = feature.copy()
    location = result.current.location
    location_name = _location_name(copy, location)
    reply = (
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
            _append_location(reply, copy, index, nearby)
    else:
        reply.line(copy.overview_no_locations)
    reply.section(copy.overview_current_section, icon=copy.navigation_icon)
    reply.field(copy.overview_current_label, location_name)
    reply.row(
        (copy.region_label, location.region),
        (copy.terrain_label, location.terrain),
    )
    return reply.actions(
        _message_actions(feature.nearby_overview_actions(result.locations))
    ).build()


def _nearby_cultivators_message(feature: PositionFeature, result: NearbyCultivatorPage):
    copy = feature.copy()
    reply = M.document().header(copy.cultivators_title)
    if result.active_companion is not None:
        reply.section(copy.cultivators_active_section, icon=copy.cultivator_icon).field(
            result.active_companion.name,
            copy.cultivator_summary.format(
                境界=result.active_companion.realm_name,
                等级=result.active_companion.level,
                性别=result.active_companion.gender,
                状态="",
            ),
        )
    if result.local_cultivators:
        reply.section(copy.cultivators_local_section, icon=copy.cultivator_icon)
        for local in result.local_cultivators:
            reply.field(
                local.name,
                copy.cultivator_summary.format(
                    境界=local.realm_name,
                    等级=local.level,
                    性别=local.gender,
                    状态="",
                ),
            ).line(local.description)
    reply.section(copy.cultivators_visiting_section, icon=copy.navigation_icon)
    if result.cultivators:
        for cultivator in result.cultivators:
            state = copy.state_separator.join(cultivator.states)
            state_text = copy.state_prefix.format(状态=state) if state else ""
            reply.field(
                cultivator.name,
                copy.cultivator_summary.format(
                    境界=cultivator.realm_name,
                    等级=cultivator.level,
                    性别=cultivator.gender,
                    状态=state_text,
                ),
            ).line(
                copy.cultivator_direction.format(
                    方向=cultivator.direction,
                    距离=cultivator.distance,
                )
                if cultivator.direction
                else copy.colocated_cultivator_direction.format(
                    距离=cultivator.distance
                )
            )
    else:
        reply.line(copy.cultivators_empty)
    reply.section(copy.cultivators_page_section, icon=copy.page_icon).field(
        copy.cultivators_current_label, result.page
    )
    if result.truncated:
        reply.line(copy.cultivators_truncated)
    return reply.actions(
        _message_actions(
            feature.nearby_cultivator_actions(result.page, result.has_next)
        )
    ).build()


def _nearby_locations_message(feature: PositionFeature, result: NearbyWorldLocations):
    copy = feature.copy()
    reply = (
        M.document()
        .header(copy.locations_title)
        .section(copy.locations_section, icon=copy.location_icon)
    )
    if not result.values:
        reply.line(copy.locations_empty)
    for index, location in enumerate(result.values, start=1):
        _append_location(reply, copy, index, location)
    return reply.actions(
        _message_actions(feature.nearby_location_actions(result.values))
    ).build()


def _append_location(
    reply, copy: PositionCopy, index: int, location: NearbyWorldLocation
) -> None:
    functions = (
        copy.function_separator.join(location.functions) or copy.no_available_function
    )
    reply.item(
        index,
        copy.location_summary.format(
            名称=location.name,
            方向=location.direction,
            距离=location.distance,
        ),
    ).line(
        copy.location_detail.format(
            区域=location.region,
            地形=location.terrain,
            功能=functions,
        )
    )


def _location_name(copy: PositionCopy, location) -> str:
    if location.location_name:
        return location.location_name
    return copy.unknown_location.format(区域=location.region, 地形=location.terrain)


def _coordinate(copy: PositionCopy, xy: tuple[int, int]) -> str:
    return copy.coordinate.format(横坐标=xy[0], 纵坐标=xy[1])


def _message_actions(actions: tuple[PositionAction, ...]) -> tuple[Action, ...]:
    return tuple(
        Action(
            action.action_id,
            action.label,
            action.command,
            behavior=action.behavior,
            style=action.style,
        )
        for action in actions
    )


__all__ = []
