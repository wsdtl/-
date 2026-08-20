"""托管控制核心：保存会话事实并原子切换所有参与者的控制状态。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from game.core.action_group import ActionGroupError, ActionGroupService
from game.core.data import JsonDataError, JsonDataService
from game.core.database import DatabaseService, TransactionCommand
from game.core.player_state import (
    PlayerStateService,
    StateTransitionCommand,
)

from .contracts import HostingError, HostingServiceStatus, HostingSession

CONTROL_TYPE = "控制"


class HostingService:
    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        player_state: PlayerStateService,
        action_group: ActionGroupService,
    ) -> None:
        self._data = data
        self._database = database
        self._player_state = player_state
        self._action_group = action_group
        self._initialized = False
        self._control_states: Mapping[str, str] = MappingProxyType({})
        self._mode_names: Mapping[str, str] = MappingProxyType({})
        self._role_names: Mapping[str, str] = MappingProxyType({})
        self._context_fields = frozenset()

    def initialize(self) -> HostingServiceStatus:
        if self._initialized:
            raise RuntimeError("托管核心微服务已经初始化")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于托管核心启动")
        if not self._player_state.status().initialized:
            raise RuntimeError("玩家状态核心必须先于托管核心启动")
        if not self._action_group.status().initialized:
            raise RuntimeError("行动编排核心必须先于托管核心启动")
        rule = _mapping(self._data.dataset("托管规则").get("托管"), "托管.json")
        control_states = _string_mapping(rule.get("控制状态"), "托管.控制状态")
        mode_names = _string_mapping(rule.get("同行类型"), "托管.同行类型")
        role_names = _string_mapping(rule.get("托管身份"), "托管.托管身份")
        context_fields = frozenset(_strings(rule.get("上下文字段"), "托管.上下文字段"))
        if set(control_states) != {"自主", "托管中"}:
            raise JsonDataError("托管.控制状态必须完整包含自主和托管中")
        if set(mode_names) != {"personal", "team", "sect"}:
            raise JsonDataError("托管.同行类型必须完整包含personal、team、sect")
        if set(role_names) != {"personal", "leader", "follower"}:
            raise JsonDataError("托管.托管身份定义不完整")
        if context_fields != {
            "托管编号",
            "托管身份",
            "托管领队",
            "同行类型",
            "同行编号",
        }:
            raise JsonDataError("托管.上下文字段定义不完整")
        for name, state_id in control_states.items():
            state = self._data.entity("人物状态", state_id)
            if state.get("名称") != name:
                raise JsonDataError(f"托管控制状态与人物状态不一致：{name}")
        self._control_states = MappingProxyType(control_states)
        self._mode_names = MappingProxyType(mode_names)
        self._role_names = MappingProxyType(role_names)
        self._context_fields = context_fields
        self._initialized = True
        return self.status()

    def status(self) -> HostingServiceStatus:
        return HostingServiceStatus(self._initialized, self._control_states)

    async def start(self, user_id: str, request_id: str) -> HostingSession:
        self._require_initialized()
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "托管:启动":
                raise HostingError("request_conflict")
            return _session_from_payload(committed.payload)
        try:
            group = await self._action_group.resolve(user_id)
        except ActionGroupError as exc:
            raise HostingError(exc.code) from exc
        if group.mode != "personal" and group.leader_user_id != user_id:
            raise HostingError("member_cannot_start")

        snapshots = await self._player_state.current_many(group.participant_user_ids)
        if len(snapshots) != len(group.participant_user_ids):
            raise HostingError("state_incomplete")
        for snapshot in snapshots:
            guard = await self._player_state.authorize(snapshot.user_id, "可开启托管")
            if not guard.allowed:
                raise HostingError(
                    "already_hosting"
                    if snapshot.states[CONTROL_TYPE].state_id
                    == self._control_states["托管中"]
                    else "participant_busy"
                )

        session_id = f"host-{user_id}-{request_id}"
        operations = []
        for snapshot in snapshots:
            role = (
                self._role_names["personal"]
                if group.mode == "personal"
                else (
                    self._role_names["leader"]
                    if snapshot.user_id == group.leader_user_id
                    else self._role_names["follower"]
                )
            )
            plan = await self._player_state.plan_transition(
                StateTransitionCommand(
                    snapshot.user_id,
                    "托管计划",
                    CONTROL_TYPE,
                    self._control_states["托管中"],
                    {
                        "托管编号": session_id,
                        "托管身份": role,
                        "托管领队": group.leader_user_id
                        if group.mode != "personal"
                        else None,
                        "同行类型": self._mode_names[group.mode],
                        "同行编号": group.group_id or None,
                    },
                    expected_version=snapshot.version,
                )
            )
            operations.append(plan.mutation)
        await self._database.commit(
            TransactionCommand(
                user_id=user_id,
                request_id=request_id,
                business_type="托管:启动",
                operations=tuple(operations),
                payload={
                    "托管编号": session_id,
                    "同行类型": group.mode,
                    "托管领队": group.leader_user_id,
                    "参与者": group.participant_user_ids,
                },
            )
        )
        return HostingSession(
            session_id, group.mode, group.leader_user_id, group.participant_user_ids
        )

    async def cancel(self, user_id: str, request_id: str) -> HostingSession:
        self._require_initialized()
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "托管:取消":
                raise HostingError("request_conflict")
            return _session_from_payload(committed.payload)
        try:
            group = await self._action_group.group_for_user(user_id)
        except ActionGroupError as exc:
            raise HostingError(exc.code) from exc
        snapshots = await self._player_state.current_many(group.participant_user_ids)
        if len(snapshots) != len(group.participant_user_ids):
            raise HostingError("state_incomplete")
        hosting = [
            snapshot
            for snapshot in snapshots
            if snapshot.states[CONTROL_TYPE].state_id == self._control_states["托管中"]
        ]
        if not hosting:
            raise HostingError("not_hosting")
        session_id = str(hosting[0].states[CONTROL_TYPE].context.get("托管编号") or "")
        self._validate_session(group, hosting, session_id)
        actor_snapshot = next(
            snapshot for snapshot in snapshots if snapshot.user_id == user_id
        )
        actor_context = actor_snapshot.states[CONTROL_TYPE].context
        leader = str(actor_context.get("托管领队") or user_id)
        if group.mode != "personal" and user_id != leader:
            raise HostingError("member_cannot_cancel")
        if len(hosting) != len(snapshots):
            raise HostingError("session_invalid")

        operations = []
        for snapshot in snapshots:
            plan = await self._player_state.plan_transition(
                StateTransitionCommand(
                    snapshot.user_id,
                    "托管计划",
                    CONTROL_TYPE,
                    self._control_states["自主"],
                    {},
                    expected_version=snapshot.version,
                )
            )
            operations.append(plan.mutation)
        await self._database.commit(
            TransactionCommand(
                user_id=user_id,
                request_id=request_id,
                business_type="托管:取消",
                operations=tuple(operations),
                payload={
                    "托管编号": session_id,
                    "同行类型": group.mode,
                    "托管领队": group.leader_user_id,
                    "参与者": group.participant_user_ids,
                },
            )
        )
        return HostingSession(
            session_id, group.mode, group.leader_user_id, group.participant_user_ids
        )

    async def current(self, user_id: str) -> HostingSession | None:
        self._require_initialized()
        snapshot = await self._player_state.current(user_id)
        if (
            snapshot is None
            or snapshot.states[CONTROL_TYPE].state_id != self._control_states["托管中"]
        ):
            return None
        context = snapshot.states[CONTROL_TYPE].context
        session_id = str(context.get("托管编号") or "")
        if not session_id:
            raise HostingError("session_invalid")
        group = await self._action_group.group_for_user(user_id)
        snapshots = await self._player_state.current_many(group.participant_user_ids)
        hosting = [
            value
            for value in snapshots
            if value.states[CONTROL_TYPE].state_id == self._control_states["托管中"]
        ]
        self._validate_session(group, hosting, session_id)
        return HostingSession(
            session_id, group.mode, group.leader_user_id, group.participant_user_ids
        )

    def _validate_session(self, group, snapshots, session_id: str) -> None:
        if not session_id or len(snapshots) != len(group.participant_user_ids):
            raise HostingError("session_invalid")
        expected_leader = group.leader_user_id if group.mode != "personal" else None
        expected_group_id = group.group_id or None
        for snapshot in snapshots:
            context = snapshot.states[CONTROL_TYPE].context
            expected_role = (
                self._role_names["personal"]
                if group.mode == "personal"
                else self._role_names[
                    "leader" if snapshot.user_id == group.leader_user_id else "follower"
                ]
            )
            if (
                set(context) != self._context_fields
                or context.get("托管编号") != session_id
                or context.get("托管身份") != expected_role
                or context.get("托管领队") != expected_leader
                or context.get("同行类型") != self._mode_names[group.mode]
                or context.get("同行编号") != expected_group_id
            ):
                raise HostingError("session_invalid")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("托管核心微服务尚未初始化")


__all__ = ["HostingService"]


def _session_from_payload(payload) -> HostingSession:
    session_id = str(payload.get("托管编号") or "").strip()
    mode = str(payload.get("同行类型") or "").strip()
    leader = str(payload.get("托管领队") or "").strip()
    raw_participants = payload.get("参与者")
    if (
        not session_id
        or mode not in {"personal", "team", "sect"}
        or not leader
        or not isinstance(raw_participants, (list, tuple))
    ):
        raise HostingError("transaction_invalid")
    participants = tuple(str(value or "").strip() for value in raw_participants)
    if not participants or any(not value for value in participants):
        raise HostingError("transaction_invalid")
    return HostingSession(session_id, mode, leader, participants)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _string_mapping(value: object, label: str) -> dict[str, str]:
    raw = _mapping(value, label)
    result = {str(key): str(item or "").strip() for key, item in raw.items()}
    if any(not key or not item for key, item in result.items()):
        raise JsonDataError(f"{label}不能包含空键或空值")
    return result


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是字符串数组")
    result = tuple(str(item or "").strip() for item in value)
    if (
        not result
        or any(not item for item in result)
        or len(result) != len(set(result))
    ):
        raise JsonDataError(f"{label}不能包含空值或重复值")
    return result
