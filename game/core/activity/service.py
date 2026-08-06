"""由 JSON 驱动的人物行为状态服务。

服务拥有状态转换规则和状态写入流程；命令层只负责把消息入口交给这里判断。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from game.core.data import JsonDataError, JsonDataService, materialize
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateMutation,
    TransactionCommand,
)

from .contracts import (
    ActivityAccessResult,
    ActivityCharacterMissingError,
    ActivityConflictError,
    ActivityRuleError,
    ActivityServiceStatus,
    ActivityTransitionCommand,
    ActivityTransitionResult,
    CharacterActivity,
)

STATE_TYPE = "character_status"
STATE_KEY = "main"


class ActivityService:
    """人物行为状态的唯一解释与写入服务。"""

    def __init__(self, data: JsonDataService, database: DatabaseService) -> None:
        self._data = data
        self._database = database
        self._initialized = False
        self._initial = ""
        self._states: Mapping[str, Mapping[str, Any]] = MappingProxyType({})
        self._access_rules: Mapping[str, Mapping[str, Any]] = MappingProxyType({})

    def initialize(self) -> ActivityServiceStatus:
        if self._initialized:
            raise RuntimeError("人物状态微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于人物状态服务启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于人物状态服务启动")

        document = self._data.dataset("人物状态规则").get("人物状态")
        if not isinstance(document, Mapping):
            raise JsonDataError("人物状态规则缺少人物状态.json")
        initial = _text(document.get("初始状态"), "人物状态.json.初始状态")
        states = _mapping(document.get("状态"), "人物状态.json.状态")
        access_rules = _mapping(document.get("准入规则"), "人物状态.json.准入规则")
        self._validate_definition(initial, states, access_rules)

        role_rule = self._data.dataset("角色规则").get("人物")
        if not isinstance(role_rule, Mapping):
            raise JsonDataError("角色规则缺少人物.json")
        role_initial = _text(role_rule.get("状态"), "人物.json.状态")
        if role_initial != initial:
            raise JsonDataError(
                f"人物.json.状态 与人物状态规则.初始状态不一致：{role_initial} != {initial}"
            )

        self._initial = initial
        self._states = MappingProxyType(
            {name: MappingProxyType(materialize(rule)) for name, rule in states.items()}
        )
        self._access_rules = MappingProxyType(
            {
                name: MappingProxyType(materialize(rule))
                for name, rule in access_rules.items()
            }
        )
        self._initialized = True
        return self.status()

    def status(self) -> ActivityServiceStatus:
        return ActivityServiceStatus(
            initialized=self._initialized,
            initial_status=self._initial if self._initialized else "",
            status_count=len(self._states),
            access_rule_count=len(self._access_rules),
        )

    def initial_mutation(self) -> StateMutation:
        """返回创建人物时要并入总事务的初始状态写入。"""

        self._require_initialized()
        return StateMutation(STATE_TYPE, STATE_KEY, {"名称": self._initial, "上下文": {}}, 0)

    async def current(self, user_id: str) -> CharacterActivity | None:
        self._require_initialized()
        snapshot = await self._database.get(StateAddress(user_id, STATE_TYPE, STATE_KEY))
        if snapshot is None:
            return None
        name, context = self._state_value(snapshot.value)
        if name not in self._states:
            raise ActivityRuleError(f"数据库中的人物状态未定义：{name}")
        return CharacterActivity(
            user_id=user_id,
            name=name,
            context=MappingProxyType(context),
            version=snapshot.version,
            updated_at=snapshot.updated_at,
        )

    async def authorize(self, user_id: str, rule_name: str) -> ActivityAccessResult:
        """按 JSON 中的准入规则判断命令是否可以作用于当前人物。"""

        self._require_initialized()
        rule = self._access_rules.get(str(rule_name or "").strip())
        if rule is None:
            raise ActivityRuleError(f"未知人物状态准入规则：{rule_name}")
        activity = await self.current(user_id)
        allowed_states = tuple(str(value) for value in rule["允许状态"])
        if activity is None:
            if bool(rule["允许未创建"]):
                return ActivityAccessResult(True)
            return ActivityAccessResult(False, "尚未创建人物", None)
        if bool(rule["允许全部状态"]) or activity.name in allowed_states:
            return ActivityAccessResult(True, current=activity.name)
        return ActivityAccessResult(False, f"当前正在{activity.name}，不能执行此命令", activity.name)

    async def enter(self, command: ActivityTransitionCommand) -> ActivityTransitionResult:
        self._require_initialized()
        target = _text(command.target, "目标状态")
        target_rule = self._states.get(target)
        if target_rule is None:
            raise ActivityRuleError(f"未知人物状态：{target}")
        activity = await self.current(command.user_id)
        if activity is None:
            raise ActivityCharacterMissingError("尚未创建人物")
        current_rule = self._states[activity.name]
        if target == activity.name:
            raise ActivityConflictError(f"人物已经处于{target}")
        if target not in tuple(current_rule["可转入"]):
            raise ActivityConflictError(f"人物当前状态{activity.name}不能进入{target}")
        expected = activity.version if command.expected_version is None else command.expected_version
        context = materialize(_mapping(command.context, "人物状态上下文"))
        receipt = await self._database.commit(
            TransactionCommand(
                user_id=command.user_id,
                request_id=command.request_id,
                business_type="人物状态:进入",
                mutations=(
                    StateMutation(
                        STATE_TYPE,
                        STATE_KEY,
                        {"名称": target, "上下文": context},
                        expected,
                    ),
                ),
                payload={"前状态": activity.name, "后状态": target},
            )
        )
        return ActivityTransitionResult(
            command.user_id, activity.name, target, expected + 1, receipt.replayed
        )

    async def interrupt(
        self,
        user_id: str,
        request_id: str,
        *,
        expected_version: int | None = None,
    ) -> ActivityTransitionResult:
        """只在 JSON 明确允许时中断当前行为并回到结束状态。"""

        self._require_initialized()
        activity = await self.current(user_id)
        if activity is None:
            raise ActivityCharacterMissingError("尚未创建人物")
        if not bool(self._states[activity.name]["可中断"]):
            raise ActivityConflictError(f"人物当前状态{activity.name}不能中断")
        return await self._leave(
            activity,
            request_id,
            business_type="人物状态:中断",
            expected_version=expected_version,
        )

    async def finish(
        self,
        user_id: str,
        request_id: str,
        *,
        expected_version: int | None = None,
    ) -> ActivityTransitionResult:
        self._require_initialized()
        activity = await self.current(user_id)
        if activity is None:
            raise ActivityCharacterMissingError("尚未创建人物")
        return await self._leave(
            activity,
            request_id,
            business_type="人物状态:结束",
            expected_version=expected_version,
        )

    async def _leave(
        self,
        activity: CharacterActivity,
        request_id: str,
        *,
        business_type: str,
        expected_version: int | None,
    ) -> ActivityTransitionResult:
        target = self._states[activity.name].get("结束后")
        if target is None:
            raise ActivityConflictError(f"人物当前状态{activity.name}不能结束")
        expected = activity.version if expected_version is None else expected_version
        receipt = await self._database.commit(
            TransactionCommand(
                user_id=activity.user_id,
                request_id=request_id,
                business_type=business_type,
                mutations=(
                    StateMutation(
                        STATE_TYPE,
                        STATE_KEY,
                        {"名称": str(target), "上下文": {}},
                        expected,
                    ),
                ),
                payload={"前状态": activity.name, "后状态": str(target)},
            )
        )
        return ActivityTransitionResult(
            activity.user_id,
            activity.name,
            str(target),
            expected + 1,
            receipt.replayed,
        )

    def _validate_definition(
        self,
        initial: str,
        states: Mapping[str, object],
        access_rules: Mapping[str, object],
    ) -> None:
        if initial not in states:
            raise ActivityRuleError("人物状态规则的初始状态未定义")
        if not states:
            raise ActivityRuleError("人物状态规则不能为空")
        for name, raw in states.items():
            rule = _mapping(raw, f"人物状态.json.状态.{name}")
            ending = rule.get("结束后")
            if ending is not None and _text(ending, f"状态.{name}.结束后") not in states:
                raise ActivityRuleError(f"状态{name}的结束后状态不存在")
            if not isinstance(rule.get("可中断"), bool):
                raise ActivityRuleError(f"状态{name}.可中断必须是布尔值")
            transitions = _strings(rule.get("可转入"))
            unknown = set(transitions) - set(states)
            if unknown:
                raise ActivityRuleError(f"状态{name}.可转入包含未知状态：{'、'.join(sorted(unknown))}")
        for name, raw in access_rules.items():
            rule = _mapping(raw, f"人物状态.json.准入规则.{name}")
            if not isinstance(rule.get("允许未创建"), bool):
                raise ActivityRuleError(f"准入规则{name}.允许未创建必须是布尔值")
            if not isinstance(rule.get("允许全部状态"), bool):
                raise ActivityRuleError(f"准入规则{name}.允许全部状态必须是布尔值")
            allowed = _strings(rule.get("允许状态"))
            unknown = set(allowed) - set(states)
            if unknown:
                raise ActivityRuleError(f"准入规则{name}包含未知状态：{'、'.join(sorted(unknown))}")

    @staticmethod
    def _state_value(value: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        name = _text(value.get("名称"), "人物状态.名称")
        context = value.get("上下文", {})
        return name, dict(_mapping(context, "人物状态.上下文"))

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("人物状态微服务尚未初始化")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ActivityRuleError(f"{label}必须是对象")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActivityRuleError(f"{label}必须是非空字符串")
    return value.strip()


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ActivityRuleError("状态引用必须是字符串数组")
    result = tuple(_text(item, "状态引用") for item in value)
    if len(result) != len(set(result)):
        raise ActivityRuleError("状态引用不能重复")
    return result


__all__ = ["STATE_KEY", "STATE_TYPE", "ActivityService"]
