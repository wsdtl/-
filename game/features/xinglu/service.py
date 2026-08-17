"""即时行路的世界规划与人物迁移编排。"""

from __future__ import annotations

from game.core.character import CharacterService
from game.core.data import JsonDataError
from game.core.location import (
    GroupLocationMoveCommand,
    LocationConflictError,
    LocationService,
)
from game.core.team import TeamError, TeamService
from game.core.world import JourneyQuery, LocationQuery, WorldService

from .contracts import (
    TravelConflictError,
    TravelQueryError,
    TravelRequest,
    TravelResult,
)


class TravelFeature:
    """即时完成一次行程，不持有路线或人物状态。"""

    def __init__(
        self,
        world: WorldService,
        character: CharacterService,
        location: LocationService,
        team: TeamService,
    ) -> None:
        self._world = world
        self._character = character
        self._location = location
        self._team = team
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("行路玩法微服务已经初始化")
        if not self._world.status().initialized:
            raise RuntimeError("世界核心必须先于行路玩法启动")
        if not self._character.status().initialized:
            raise RuntimeError("角色核心必须先于行路玩法启动")
        if not self._location.status().initialized:
            raise RuntimeError("玩家位置核心必须先于行路玩法启动")
        if not self._team.status().initialized:
            raise RuntimeError("队伍核心必须先于行路玩法启动")
        self._initialized = True

    async def travel(self, request: TravelRequest) -> TravelResult:
        if not self._initialized:
            raise RuntimeError("行路玩法微服务尚未初始化")
        destination = _destination_query(request.destination)
        try:
            participants = await self._team.action_participants(request.user_id)
        except TeamError as exc:
            if exc.code == "member_cannot_start":
                raise TravelQueryError("只有队长可以带队行路") from exc
            raise TravelConflictError("队伍状态刚刚发生变化") from exc
        public_profiles = await self._character.public_profiles((request.user_id,))
        if not public_profiles:
            raise TravelQueryError("尚未创建人物")
        character = public_profiles[0]
        current = await self._location.current(request.user_id)
        try:
            plan = self._world.plan_journey(
                JourneyQuery(
                    origin_xy=current.xy,
                    destination=destination,
                    realm_id=character.realm_id,
                )
            )
        except (JsonDataError, ValueError) as exc:
            message = str(exc)
            if "起点与终点" in message:
                message = "你已经身在此处，无须再次动身。"
            raise TravelQueryError(message) from exc
        try:
            moved = await self._location.move_many(
                GroupLocationMoveCommand(
                    owner_user_id=request.user_id,
                    request_id=request.request_id,
                    participant_user_ids=participants,
                    expected_origin_xy=current.xy,
                    destination_xy=plan.destination.xy,
                )
            )
        except LocationConflictError as exc:
            raise TravelConflictError(str(exc)) from exc
        if not moved.changed:
            raise TravelQueryError("你已经身在此处，无须再次动身。")
        return TravelResult(
            plan=plan,
            participant_user_ids=participants,
            replayed=moved.replayed,
        )


def _destination_query(value: object) -> LocationQuery:
    parts = str(value or "").split()
    if len(parts) == 1:
        return LocationQuery(location_name=parts[0])
    if len(parts) == 2:
        try:
            return LocationQuery(xy=(int(parts[0]), int(parts[1])))
        except ValueError as exc:
            raise TravelQueryError("坐标必须写成两个整数，例如：去 45 62") from exc
    raise TravelQueryError("目的地只能写地点名或一组 xy 坐标")


__all__ = ["TravelFeature"]
