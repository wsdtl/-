"""由位置 JSON 规则驱动的玩家地表位置服务。"""

from __future__ import annotations

from collections.abc import Mapping

from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    LocationMutation,
    StateConflictError,
    TransactionCommand,
)
from game.core.world import LocationQuery, WorldService

from .contracts import (
    LocationConflictError,
    LocationMissingError,
    LocationMoveCommand,
    LocationMoveResult,
    LocationServiceStatus,
    NearbyPlayerCandidates,
    NearbyPlayerLocation,
    PlayerLocation,
)


class LocationService:
    """拥有玩家地表位置写权限和空间范围查询权的唯一核心服务。"""

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        world: WorldService,
    ) -> None:
        self._data = data
        self._database = database
        self._world = world
        self._initialized = False
        self._radius_meters = 0
        self._page_size = 0
        self._visible_limit = 0
        self._candidate_limit = 0
        self._cell_size_meters = 0

    def initialize(self) -> LocationServiceStatus:
        if self._initialized:
            raise RuntimeError("玩家位置核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于玩家位置服务启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于玩家位置服务启动")
        if not self._world.status().initialized:
            raise RuntimeError("世界核心必须先于玩家位置服务启动")
        rules = self._data.dataset("位置规则")
        nearby = rules.get("附近")
        if not isinstance(nearby, Mapping):
            raise JsonDataError("位置规则缺少附近.json")
        cultivators = _mapping(nearby.get("修士"), "附近.修士")
        self._radius_meters = _positive_int(
            cultivators.get("范围米数"), "附近.修士.范围米数"
        )
        self._page_size = _positive_int(
            cultivators.get("每页数量"), "附近.修士.每页数量"
        )
        self._visible_limit = _positive_int(
            cultivators.get("最多可见数量"), "附近.修士.最多可见数量"
        )
        self._candidate_limit = _positive_int(
            cultivators.get("最多候选数量"), "附近.修士.最多候选数量"
        )
        if self._page_size > self._visible_limit:
            raise JsonDataError("附近修士每页数量不能超过最多可见数量")
        if self._visible_limit > self._candidate_limit:
            raise JsonDataError("附近修士最多可见数量不能超过最多候选数量")
        self._cell_size_meters = self._world.map_view().cell_size_meters
        self._initialized = True
        return self.status()

    def status(self) -> LocationServiceStatus:
        location_count = (
            self._database.status().location_count if self._initialized else 0
        )
        return LocationServiceStatus(
            initialized=self._initialized,
            player_count=location_count,
            nearby_radius_meters=self._radius_meters,
            nearby_page_size=self._page_size,
            nearby_visible_limit=self._visible_limit,
        )

    def initial_mutation(self, user_id: str, xy: tuple[int, int]) -> LocationMutation:
        self._require_initialized()
        normalized_user_id = _text(user_id, "user_id")
        validated = self._world.locate(LocationQuery(xy=_xy(xy))).xy
        return LocationMutation(normalized_user_id, validated, 0)

    async def current(self, user_id: str) -> PlayerLocation:
        self._require_initialized()
        normalized_user_id = _text(user_id, "user_id")
        record = await self._database.get_location(normalized_user_id)
        if record is None:
            raise LocationMissingError("人物缺少地表位置")
        return PlayerLocation(
            record.user_id,
            record.xy,
            record.version,
            record.updated_at,
        )

    async def nearby_players(self, user_id: str) -> NearbyPlayerCandidates:
        self._require_initialized()
        origin = await self.current(user_id)
        records = await self._database.nearby_locations(
            origin_xy=origin.xy,
            radius_meters=self._radius_meters,
            cell_size_meters=self._cell_size_meters,
            limit=self._candidate_limit + 1,
            exclude_user_id=origin.user_id,
        )
        limit_reached = len(records) > self._candidate_limit
        origin_altitude = self._world.locate(LocationQuery(xy=origin.xy)).altitude
        values: list[NearbyPlayerLocation] = []
        for value in records[: self._candidate_limit]:
            altitude = self._world.locate(LocationQuery(xy=value.xy)).altitude
            distance_squared = (
                value.horizontal_distance_squared_meters
                + (altitude - origin_altitude) ** 2
            )
            if distance_squared <= self._radius_meters**2:
                values.append(
                    NearbyPlayerLocation(value.user_id, value.xy, distance_squared)
                )
        values.sort(
            key=lambda value: (
                value.distance_squared_meters,
                value.xy,
                value.user_id,
            )
        )
        return NearbyPlayerCandidates(
            origin=origin,
            values=tuple(values),
            candidate_limit_reached=limit_reached,
            page_size=self._page_size,
            visible_limit=self._visible_limit,
        )

    async def move(self, command: LocationMoveCommand) -> LocationMoveResult:
        self._require_initialized()
        user_id = _text(command.user_id, "user_id")
        request_id = _text(command.request_id, "request_id")
        expected = self._world.locate(
            LocationQuery(xy=_xy(command.expected_origin_xy))
        ).xy
        destination = self._world.locate(
            LocationQuery(xy=_xy(command.destination_xy))
        ).xy
        current = await self.current(user_id)
        if current.xy == destination:
            return LocationMoveResult(user_id, current.xy, destination, False, False)
        if current.xy != expected:
            raise LocationConflictError(
                f"人物位置已经改变：预期 {expected}，当前 {current.xy}"
            )
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=user_id,
                    request_id=request_id,
                    business_type="人物行路",
                    operations=(
                        LocationMutation(user_id, destination, current.version),
                    ),
                    payload={"起点": list(current.xy), "终点": list(destination)},
                )
            )
        except StateConflictError as exc:
            raise LocationConflictError("人物位置在行路结算前已经改变") from exc
        return LocationMoveResult(
            user_id,
            current.xy,
            destination,
            True,
            receipt.replayed,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("玩家位置核心微服务尚未初始化")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _text(value: object, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized != value:
        raise ValueError(f"{label}必须是无首尾空白的非空字符串")
    return normalized


def _xy(value: object) -> tuple[int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise ValueError("xy必须是两个整数")
    return int(value[0]), int(value[1])


__all__ = ["LocationService"]
