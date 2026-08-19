"""由 JSON 驱动的宗门主体与成员关系核心。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    SharedConstraintError,
    SharedEntityMutation,
    SharedLocationMutation,
    SharedMemberMutation,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.player_state import PlayerStateService

from .contracts import (
    SectConflictError,
    SectError,
    SectInvitation,
    SectMember,
    SectServiceStatus,
    SectSnapshot,
)

ENTITY_TYPE = "宗门"
INVITATION_STATE = "sect_invite"
MAIN_KEY = "main"


class SectService:
    state_types = frozenset({INVITATION_STATE})

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        player_state: PlayerStateService,
    ) -> None:
        self._data = data
        self._database = database
        self._player_state = player_state
        self._initialized = False
        self._maximum_followers = 0
        self._invitation_seconds = 0
        self._guard_rule = ""
        self._leader_role = ""
        self._member_role = ""
        self._name_min = 0
        self._name_max = 0
        self._name_pattern = ""

    def initialize(self) -> SectServiceStatus:
        if self._initialized:
            raise RuntimeError("宗门核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于宗门核心启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于宗门核心启动")
        rule = _mapping(self._data.dataset("宗门规则").get("宗门"), "宗门.json")
        name = _mapping(rule.get("名称"), "宗门.名称")
        creation = _mapping(rule.get("创建"), "宗门.创建")
        members = _mapping(rule.get("成员"), "宗门.成员")
        invitation = _mapping(rule.get("邀请"), "宗门.邀请")
        roles = _mapping(rule.get("身份"), "宗门.身份")
        self._name_min = _positive_int(name.get("最短长度"), "宗门.名称.最短长度")
        self._name_max = _positive_int(name.get("最长长度"), "宗门.名称.最长长度")
        self._name_pattern = _text(name.get("匹配"), "宗门.名称.匹配")
        self._maximum_followers = _positive_int(
            members.get("宗门同行上限"), "宗门.成员.宗门同行上限"
        )
        self._invitation_seconds = _positive_int(
            invitation.get("有效秒数"), "宗门.邀请.有效秒数"
        )
        self._guard_rule = _text(creation.get("状态守卫"), "宗门.创建.状态守卫")
        self._leader_role = _text(roles.get("宗主"), "宗门.身份.宗主")
        self._member_role = _text(roles.get("成员"), "宗门.身份.成员")
        self._initialized = True
        return self.status()

    def status(self) -> SectServiceStatus:
        return SectServiceStatus(
            self._initialized,
            self._maximum_followers,
            self._invitation_seconds,
        )

    async def membership(self, user_id: str) -> SectMember | None:
        self._require_initialized()
        record = await self._database.get_shared_member(ENTITY_TYPE, _text(user_id, "user_id"))
        if record is None:
            return None
        return SectMember(
            record.entity_id,
            record.user_id,
            record.role,
            record.join_order,
            record.version,
        )

    async def sect(self, sect_id: str) -> SectSnapshot | None:
        self._require_initialized()
        record = await self._database.get_shared_entity(ENTITY_TYPE, _text(sect_id, "sect_id"))
        if record is None:
            return None
        value = record.value
        entrance = value.get("入口坐标")
        if not isinstance(entrance, (list, tuple)) or len(entrance) != 2:
            raise SectError("sect_snapshot_invalid")
        return SectSnapshot(
            record.entity_id,
            _text(value.get("名称"), "宗门.名称"),
            _text(value.get("宗主"), "宗门.宗主"),
            _text(value.get("洞天编号"), "宗门.洞天编号"),
            (int(entrance[0]), int(entrance[1])),
            record.version,
        )

    async def members(self, sect_id: str) -> tuple[SectMember, ...]:
        rows = await self._database.list_shared_members(ENTITY_TYPE, _text(sect_id, "sect_id"))
        return tuple(
            SectMember(row.entity_id, row.user_id, row.role, row.join_order, row.version)
            for row in rows
        )

    async def pending_invitation(
        self, user_id: str, *, now: datetime | None = None
    ) -> SectInvitation | None:
        snapshot = await self._database.get(StateAddress(_text(user_id, "user_id"), INVITATION_STATE, MAIN_KEY))
        if snapshot is None:
            return None
        value = snapshot.value
        expires_at = _time(value.get("到期时间"), "宗门邀请.到期时间")
        current = _utc(now)
        return SectInvitation(
            _text(value.get("宗门编号"), "宗门邀请.宗门编号"),
            _text(value.get("宗门名称"), "宗门邀请.宗门名称"),
            _text(value.get("邀请者"), "宗门邀请.邀请者"),
            _text(value.get("目标"), "宗门邀请.目标"),
            expires_at,
            snapshot.version,
            current >= expires_at,
        )

    async def create(
        self, user_id: str, request_id: str, name: str, entrance_xy: tuple[int, int]
    ) -> SectSnapshot:
        self._require_initialized()
        user = _text(user_id, "user_id")
        request = _text(request_id, "request_id")
        normalized_name = self._validate_name(name)
        guard = await self._player_state.authorize(user, self._guard_rule)
        if not guard.allowed:
            raise SectConflictError("actor_busy")
        if await self.membership(user) is not None:
            raise SectConflictError("already_member")
        if await self._database.get_shared_entity_by_name(ENTITY_TYPE, normalized_name) is not None:
            raise SectConflictError("name_occupied")
        if await self._database.shared_location_at(ENTITY_TYPE, entrance_xy) is not None:
            raise SectConflictError("entrance_occupied")
        sect_id = _id("sect", user, request)
        cave_id = _id("cave", sect_id, normalized_name)
        value = {
            "编号": sect_id,
            "名称": normalized_name,
            "宗主": user,
            "洞天编号": cave_id,
            "入口坐标": list(entrance_xy),
            "成员数量": 1,
        }
        try:
            await self._database.commit(
                TransactionCommand(
                    user,
                    request,
                    "创建宗门",
                    (
                        SharedEntityMutation(ENTITY_TYPE, sect_id, value, 0),
                        SharedMemberMutation(ENTITY_TYPE, user, sect_id, self._leader_role, 1, 0),
                        SharedLocationMutation(ENTITY_TYPE, sect_id, entrance_xy, 0),
                    ),
                    {"宗门编号": sect_id, "名称": normalized_name},
                )
            )
        except SharedConstraintError as exc:
            code = "name_occupied" if "名称" in str(exc) else "entrance_occupied"
            raise SectConflictError(code) from exc
        except (StateConflictError, IdempotencyConflictError) as exc:
            raise SectConflictError("sect_changed") from exc
        return SectSnapshot(sect_id, normalized_name, user, cave_id, entrance_xy, 1)

    async def invite(self, inviter: str, target: str, request_id: str, *, now: datetime | None = None) -> SectInvitation:
        self._require_initialized()
        inviter = _text(inviter, "inviter_user_id")
        target = _text(target, "target_user_id")
        if inviter == target:
            raise SectConflictError("cannot_invite_self")
        own = await self.membership(inviter)
        if own is None:
            raise SectConflictError("not_member")
        if own.role != self._leader_role:
            raise SectConflictError("not_leader")
        if await self.membership(target) is not None:
            raise SectConflictError("target_already_member")
        existing = await self._database.get(StateAddress(target, INVITATION_STATE, MAIN_KEY))
        current = _utc(now)
        if existing is not None:
            pending = await self.pending_invitation(target, now=current)
            if pending is not None and not pending.expired:
                raise SectConflictError("pending_invitation_exists")
        sect = await self.sect(own.sect_id)
        if sect is None:
            raise SectConflictError("sect_changed")
        expires = current + timedelta(seconds=self._invitation_seconds)
        value = {
            "宗门编号": sect.sect_id,
            "宗门名称": sect.name,
            "邀请者": inviter,
            "目标": target,
            "到期时间": expires.isoformat(),
        }
        try:
            await self._database.commit(
                TransactionCommand(
                    inviter,
                    _text(request_id, "request_id"),
                    "宗门邀请",
                    (StateMutation(target, INVITATION_STATE, MAIN_KEY, value, existing.version if existing else 0),),
                    {"宗门编号": sect.sect_id, "目标": target},
                )
            )
        except (StateConflictError, IdempotencyConflictError) as exc:
            raise SectConflictError("sect_changed") from exc
        return SectInvitation(sect.sect_id, sect.name, inviter, target, expires, (existing.version if existing else 0) + 1, False)

    async def accept(self, user_id: str, request_id: str, *, now: datetime | None = None) -> SectSnapshot:
        target = _text(user_id, "user_id")
        invitation = await self.pending_invitation(target, now=now)
        if invitation is None:
            raise SectConflictError("invitation_missing")
        if invitation.expired:
            raise SectConflictError("invitation_expired")
        sect = await self.sect(invitation.sect_id)
        if sect is None:
            raise SectConflictError("invitation_expired")
        if await self.membership(target) is not None:
            raise SectConflictError("already_member")
        members = await self.members(sect.sect_id)
        value = _sect_value(sect, member_count=len(members) + 1)
        try:
            await self._database.commit(
                TransactionCommand(
                    target,
                    _text(request_id, "request_id"),
                    "接受宗门邀请",
                    (
                        SharedEntityMutation(ENTITY_TYPE, sect.sect_id, value, sect.version),
                        SharedMemberMutation(ENTITY_TYPE, target, sect.sect_id, self._member_role, len(members) + 1, 0),
                        StateMutation(target, INVITATION_STATE, MAIN_KEY, None, invitation.version),
                    ),
                    {"宗门编号": sect.sect_id, "邀请者": invitation.inviter_user_id},
                )
            )
        except (SharedConstraintError, StateConflictError, IdempotencyConflictError) as exc:
            raise SectConflictError("sect_changed") from exc
        return sect

    async def reject(self, user_id: str, request_id: str) -> None:
        target = _text(user_id, "user_id")
        invitation = await self.pending_invitation(target)
        if invitation is None:
            raise SectConflictError("invitation_missing")
        try:
            await self._database.commit(
                TransactionCommand(
                    target,
                    _text(request_id, "request_id"),
                    "拒绝宗门邀请",
                    (StateMutation(target, INVITATION_STATE, MAIN_KEY, None, invitation.version),),
                    {"宗门编号": invitation.sect_id},
                )
            )
        except (StateConflictError, IdempotencyConflictError) as exc:
            raise SectConflictError("sect_changed") from exc

    async def leave(self, user_id: str, request_id: str) -> None:
        member = await self._require_member(user_id)
        if member.role == self._leader_role:
            raise SectConflictError("leader_cannot_leave")
        await self._commit_member_delete(member, request_id, "退出宗门")

    async def kick(self, user_id: str, target: str, request_id: str) -> None:
        actor = await self._require_member(user_id)
        if actor.role != self._leader_role:
            raise SectConflictError("not_leader")
        member = await self.membership(target)
        if member is None or member.sect_id != actor.sect_id:
            raise SectConflictError("target_not_member")
        if member.role == self._leader_role:
            raise SectConflictError("cannot_remove_leader")
        await self._commit_member_delete(member, request_id, "逐出宗门")

    async def transfer(self, user_id: str, target: str, request_id: str) -> SectSnapshot:
        actor = await self._require_member(user_id)
        if actor.role != self._leader_role:
            raise SectConflictError("not_leader")
        if actor.user_id == target:
            raise SectConflictError("cannot_transfer_self")
        member = await self.membership(target)
        if member is None or member.sect_id != actor.sect_id:
            raise SectConflictError("target_not_member")
        sect_record = await self._database.get_shared_entity(ENTITY_TYPE, actor.sect_id)
        if sect_record is None:
            raise SectConflictError("sect_changed")
        value = dict(sect_record.value)
        value["宗主"] = target
        try:
            await self._database.commit(
                TransactionCommand(
                    actor.user_id,
                    _text(request_id, "request_id"),
                    "转让宗主",
                    (
                        SharedEntityMutation(ENTITY_TYPE, actor.sect_id, value, sect_record.version),
                        SharedMemberMutation(ENTITY_TYPE, actor.user_id, actor.sect_id, self._member_role, actor.join_order, actor.version),
                        SharedMemberMutation(ENTITY_TYPE, target, actor.sect_id, self._leader_role, member.join_order, member.version),
                    ),
                    {"宗门编号": actor.sect_id, "新宗主": target},
                )
            )
        except (SharedConstraintError, StateConflictError, IdempotencyConflictError) as exc:
            raise SectConflictError("sect_changed") from exc
        return SectSnapshot(sect_record.entity_id, _text(value.get("名称"), "宗门.名称"), target, _text(value.get("洞天编号"), "宗门.洞天编号"), tuple(value["入口坐标"]), sect_record.version + 1)

    async def disband(self, user_id: str, request_id: str) -> None:
        member = await self._require_member(user_id)
        if member.role != self._leader_role:
            raise SectConflictError("not_leader")
        sect_record = await self._database.get_shared_entity(ENTITY_TYPE, member.sect_id)
        location = await self._database.get_shared_location(ENTITY_TYPE, member.sect_id)
        if sect_record is None or location is None:
            raise SectConflictError("sect_changed")
        members = await self.members(member.sect_id)
        operations = [
            SharedEntityMutation(ENTITY_TYPE, member.sect_id, None, sect_record.version),
            SharedLocationMutation(ENTITY_TYPE, member.sect_id, None, location.version),
        ] + [
            SharedMemberMutation(ENTITY_TYPE, value.user_id, None, "", 1, value.version)
            for value in members
        ]
        try:
            await self._database.commit(TransactionCommand(member.user_id, _text(request_id, "request_id"), "解散宗门", tuple(operations), {"宗门编号": member.sect_id}))
        except (SharedConstraintError, StateConflictError, IdempotencyConflictError) as exc:
            raise SectConflictError("sect_changed") from exc

    async def _commit_member_delete(self, member: SectMember, request_id: str, business_type: str) -> None:
        sect = await self.sect(member.sect_id)
        if sect is None:
            raise SectConflictError("sect_changed")
        members = await self.members(member.sect_id)
        value = _sect_value(sect, member_count=len(members) - 1)
        try:
            await self._database.commit(
                TransactionCommand(
                    member.user_id,
                    _text(request_id, "request_id"),
                    business_type,
                    (
                        SharedEntityMutation(
                            ENTITY_TYPE, member.sect_id, value, sect.version
                        ),
                        SharedMemberMutation(
                            ENTITY_TYPE,
                            member.user_id,
                            None,
                            "",
                            1,
                            member.version,
                        ),
                    ),
                    {"宗门编号": member.sect_id, "目标": member.user_id},
                )
            )
        except (SharedConstraintError, StateConflictError, IdempotencyConflictError) as exc:
            raise SectConflictError("sect_changed") from exc

    async def _require_member(self, user_id: str) -> SectMember:
        member = await self.membership(_text(user_id, "user_id"))
        if member is None:
            raise SectConflictError("not_member")
        return member

    def _validate_name(self, name: str) -> str:
        normalized = _text(name, "宗门名称")
        if not self._name_min <= len(normalized) <= self._name_max:
            raise SectConflictError("name_invalid")
        import re

        if re.fullmatch(self._name_pattern, normalized) is None:
            raise SectConflictError("name_invalid")
        return normalized

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("宗门核心微服务尚未初始化")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SectError("invalid_text")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)


def _time(value: object, label: str) -> datetime:
    try:
        return _utc(datetime.fromisoformat(str(value)))
    except ValueError as exc:
        raise SectError("invitation_time_invalid") from exc


def _id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, '\\0'.join(parts)).hex[:20]}"


def _sect_value(sect: SectSnapshot, *, member_count: int) -> dict[str, object]:
    return {
        "编号": sect.sect_id,
        "名称": sect.name,
        "宗主": sect.leader_user_id,
        "洞天编号": sect.cave_id,
        "入口坐标": list(sect.entrance_xy),
        "成员数量": member_count,
    }


__all__ = ["ENTITY_TYPE", "INVITATION_STATE", "MAIN_KEY", "SectService"]
