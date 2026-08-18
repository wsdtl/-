"""采矿参与者解析与展示编排。"""

from __future__ import annotations

from datetime import datetime

from game.core.asset import AssetService
from game.core.data import JsonDataService
from game.core.gathering import (
    GatheringError,
    GatheringProgress,
    GatheringService,
    GatheringSettlement,
    GatheringStartCommand,
    GatheringStarted,
)
from game.core.team import TeamError, TeamService

from .contracts import OreGatheringAction, OreGatheringCopy, OreGatheringFeatureError
from .presentation import actions, load_presentation

KIND = "采矿"


class OreGatheringFeature:
    def __init__(
        self,
        data: JsonDataService,
        gathering: GatheringService,
        asset: AssetService,
        team: TeamService,
    ) -> None:
        self._data = data
        self._gathering = gathering
        self._asset = asset
        self._team = team
        self._copy: OreGatheringCopy | None = None
        self._buttons: tuple[dict[str, str], ...] | tuple = ()

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("采矿玩法已经初始化")
        self._gathering.mode_status(KIND)
        if not self._team.status().initialized:
            raise RuntimeError("队伍核心必须先于采矿玩法启动")
        self._copy, self._buttons = load_presentation(self._data)

    def copy(self) -> OreGatheringCopy:
        if self._copy is None:
            raise RuntimeError("采矿玩法尚未初始化")
        return self._copy

    async def start(self, user_id: str, request_id: str) -> GatheringStarted:
        try:
            participants = await self._team.action_participants(user_id)
            return await self._gathering.start(
                GatheringStartCommand(KIND, user_id, request_id, participants)
            )
        except TeamError as exc:
            message = (
                "只有队长可以带队采矿"
                if exc.code == "member_cannot_start"
                else "队伍状态刚刚发生变化"
            )
            raise OreGatheringFeatureError(message) from exc
        except (GatheringError, ValueError) as exc:
            raise OreGatheringFeatureError(str(exc)) from exc

    async def progress(
        self, user_id: str, *, now: datetime | None = None
    ) -> GatheringProgress:
        try:
            return await self._gathering.progress(KIND, user_id, now=now)
        except (GatheringError, ValueError) as exc:
            raise OreGatheringFeatureError(str(exc)) from exc

    async def settle(
        self, user_id: str, request_id: str, *, now: datetime | None = None
    ) -> GatheringSettlement:
        try:
            return await self._gathering.settle(
                KIND, user_id, request_id, now=now
            )
        except (GatheringError, ValueError) as exc:
            raise OreGatheringFeatureError(str(exc)) from exc

    def started_actions(self) -> tuple[OreGatheringAction, ...]:
        return actions(self._buttons, "开始", {"可以结束"})

    def progress_actions(self, can_end: bool) -> tuple[OreGatheringAction, ...]:
        return actions(self._buttons, "进度", {"可以结束"} if can_end else set())

    def settlement_actions(
        self, page: int, total_pages: int
    ) -> tuple[OreGatheringAction, ...]:
        conditions = set()
        if page > 1:
            conditions.add("存在上一页")
        if page < total_pages:
            conditions.add("存在下一页")
        return actions(
            self._buttons,
            "总结",
            conditions,
            {"上一页": page - 1, "下一页": page + 1},
        )

    def item_label(self, item_id: str, grade_id: str) -> str:
        item = self._data.entity("物品", item_id)
        return f"{self._asset.grade(grade_id).name}{item.get('名称') or item_id}"


__all__ = ["OreGatheringFeature"]
