"""统一解析个人、队伍和宗门同行的有效行动参与者。"""

from __future__ import annotations

from game.core.sect import SectService
from game.core.team import TeamConflictError, TeamService

from .contracts import ActionGroup, ActionGroupError, ActionGroupServiceStatus


class ActionGroupService:
    def __init__(self, team: TeamService, sect: SectService) -> None:
        self._team = team
        self._sect = sect
        self._initialized = False

    def initialize(self) -> ActionGroupServiceStatus:
        if self._initialized:
            raise RuntimeError("行动编排核心微服务已经初始化")
        if not self._team.status().initialized:
            raise RuntimeError("队伍核心必须先于行动编排核心启动")
        if not self._sect.status().initialized:
            raise RuntimeError("宗门核心必须先于行动编排核心启动")
        self._initialized = True
        return self.status()

    def status(self) -> ActionGroupServiceStatus:
        return ActionGroupServiceStatus(self._initialized)

    async def resolve(self, user_id: str) -> ActionGroup:
        self._require_initialized()
        team_membership = await self._team.membership(user_id)
        follow = await self._sect.follow_membership(user_id)
        if team_membership is not None and follow is not None:
            raise ActionGroupError("fellowship_conflict")
        if follow is not None:
            if follow.leader_user_id != user_id:
                raise ActionGroupError("member_cannot_start")
            return ActionGroup(
                "sect", follow.leader_user_id, follow.member_user_ids, follow.sect_id
            )
        try:
            participants = await self._team.action_participants(user_id)
        except TeamConflictError as exc:
            if exc.code == "member_cannot_start":
                raise ActionGroupError("member_cannot_start") from exc
            raise ActionGroupError("group_changed") from exc
        return ActionGroup(
            "team" if len(participants) > 1 else "personal",
            participants[0],
            participants,
            team_membership.team.team_id if team_membership is not None else "",
        )

    async def group_for_user(self, user_id: str) -> ActionGroup:
        """返回用户当前行动组；允许跟随者查询，但不授予发起权限。"""

        self._require_initialized()
        team_membership = await self._team.membership(user_id)
        follow = await self._sect.follow_membership(user_id)
        if team_membership is not None and follow is not None:
            raise ActionGroupError("fellowship_conflict")
        if follow is not None:
            return ActionGroup(
                "sect",
                follow.leader_user_id,
                follow.member_user_ids,
                follow.sect_id,
            )
        if team_membership is not None:
            team = team_membership.team
            return ActionGroup(
                "team" if len(team.member_user_ids) > 1 else "personal",
                team.leader_user_id,
                team.member_user_ids,
                team.team_id,
            )
        normalized = str(user_id or "").strip()
        if not normalized:
            raise ValueError("user_id不能为空")
        return ActionGroup("personal", normalized, (normalized,))

    async def participants(self, user_id: str) -> tuple[str, ...]:
        return (await self.resolve(user_id)).participant_user_ids

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("行动编排核心微服务尚未初始化")


__all__ = ["ActionGroupService"]
