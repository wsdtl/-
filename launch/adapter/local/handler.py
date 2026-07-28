"""本地命令驱动器。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, List, Optional, Pattern, Set, Tuple, Union

from launch.config import config
from launch.log import C, logger
from launch.message_events import emit_message_event, event_from_incoming

from ..base_handler import BaseMessageHandler
from ..command_guard import CommandGuardContext, run_command_guards
from ..context import (
    AdapterCapabilities,
    CONVERSATION_PRIVATE,
    MessageContext,
    ReplyTarget,
    reset_current_message_context,
    set_current_message_context,
)
from ..depends import call_with_dependencies
from .event import LocalCommandEvent, local_command_event, local_message_identity
from .manager import LocalDispatchResult, current_event, manager


Command = Union[str, Pattern]


@dataclass(frozen=True)
class LocalCommandRule:
    """一条本地命令规则。"""

    func: Callable
    priority: int
    block: bool
    order: int
    pattern: Optional[Pattern] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalCommandMatch:
    """本地消息命中命令后的临时结果。"""

    rule: LocalCommandRule
    command: str
    message: str
    match: Optional[re.Match] = None


class LocalEventHandler(BaseMessageHandler):
    """本地触发文本驱动器。"""

    CAPABILITIES = AdapterCapabilities(
        text=True,
        markdown=True,
        image=True,
        buttons=True,
        mention=False,
        private_message=True,
        group_message=False,
        active_push=False,
    )

    exact_rules: dict[str, list[LocalCommandRule]] = {}
    regex_rules: dict[str, list[LocalCommandRule]] = {}
    regex_fallback: list[LocalCommandRule] = []
    regex_prefix_lengths: Set[int] = set()
    _register_order: int = 0

    @staticmethod
    async def run() -> None:
        """启动时整理命令索引。"""

        LocalEventHandler._build_command_index()

    @staticmethod
    async def shutdown() -> None:
        """关闭本地驱动器。"""

        await manager.shutdown()

    @staticmethod
    async def dispatch(
        event: LocalCommandEvent | None = None,
        *,
        client_id: str = "",
        raw_message: str = "",
        sender_name: str = "",
        conversation_type: str = CONVERSATION_PRIVATE,
        event_id: str = "",
        bypass_guards: bool = False,
    ) -> LocalDispatchResult:
        """分发一条本地命令事件。"""

        if event is None:
            event = local_command_event(
                client_id=client_id,
                raw_message=raw_message,
                sender_name=sender_name,
                conversation_type=conversation_type,
                event_id=event_id,
                bypass_guards=bypass_guards,
            )
        elif bypass_guards and not event.bypass_guards:
            event = replace(event, bypass_guards=True)
        result = LocalDispatchResult(event=event)
        result_token = manager.bind_result(result)
        event_token = current_event.set(event)
        try:
            emit_message_event(
                event_from_incoming(
                    adapter="local",
                    client_id=event.client_id,
                    request_id=event.event_id,
                    message_type="text",
                    content=event.raw_message,
                    sender_name=event.sender_name,
                )
            )
            matched = await LocalEventHandler._match_event(event)
            result.matched = bool(matched)
            result.matched_count = len(matched)
            if not matched:
                logger.opt(colors=True).debug(
                    C.join(
                        C.warn("本地消息未命中命令"),
                        C.kv("client", event.client_id or "-"),
                        C.kv("message", LocalEventHandler._short_text(event.raw_message)),
                    )
                )
                return result

            if await LocalEventHandler._guard_blocked(matched[0], event):
                return result

            block_priority = None
            for item in matched:
                rule = item.rule
                if block_priority is not None and rule.priority < block_priority:
                    break

                await LocalEventHandler._call_rule(item, event)

                if rule.block:
                    block_priority = rule.priority

            return result
        finally:
            current_event.reset(event_token)
            manager.reset_result(result_token)

    @staticmethod
    async def _guard_blocked(item: LocalCommandMatch, event: LocalCommandEvent) -> bool:
        """命中业务回调前执行一次命令守卫。"""

        message_context = LocalEventHandler._message_context(item, event)
        context_token = set_current_message_context(message_context)
        try:
            decision = await run_command_guards(
                CommandGuardContext(
                    message_context=message_context,
                    bypass_guards=event.bypass_guards,
                    command_metadata=item.rule.metadata,
                )
            )
            if not decision.blocked:
                return False

            if decision.reply is not None:
                await manager.send(decision.reply, event.client_id)
            return True
        finally:
            reset_current_message_context(context_token)

    @staticmethod
    def handler(
        cmd: Union[Command, List[Command]],
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册本地命令处理函数。"""

        def wrapper(func: Callable) -> Callable:
            for item in LocalEventHandler._normalize_commands(cmd):
                if isinstance(item, str):
                    LocalEventHandler._register_exact_command(item, func, priority, block, metadata)
                elif isinstance(item, re.Pattern):
                    LocalEventHandler._register_regex_command(item, func, priority, block, metadata)
                else:
                    raise TypeError("cmd 只支持 str、re.Pattern，或它们组成的 list/tuple/set")
            return func

        return wrapper

    @staticmethod
    async def _match_event(event: LocalCommandEvent) -> list[LocalCommandMatch]:
        """按本地消息正文匹配已注册命令。"""

        command_text = event.raw_message.lstrip()
        if not command_text:
            return []

        command, message = LocalEventHandler._split_command(command_text)
        matched: list[LocalCommandMatch] = [
            LocalCommandMatch(rule=rule, command=command, message=message)
            for rule in LocalEventHandler.exact_rules.get(command, [])
        ]

        for rule, match in await LocalEventHandler._match_regex_command(command):
            matched.append(
                LocalCommandMatch(
                    rule=rule,
                    command=command,
                    message=LocalEventHandler._message_after_match(command_text, message, match),
                    match=match,
                )
            )

        matched.sort(key=lambda item: (-item.rule.priority, item.rule.order))
        return matched

    @staticmethod
    async def _call_rule(item: LocalCommandMatch, event: LocalCommandEvent) -> None:
        """把本地事件上下文转换成业务函数可接收的参数。"""

        message_context = LocalEventHandler._message_context(item, event)
        context_token = set_current_message_context(message_context)
        try:
            await call_with_dependencies(
                item.rule.func,
                {
                    "client_id": event.client_id,
                    "message": item.message,
                    "manager": manager,
                    "cmd": item.command,
                    "raw_message": event.raw_message,
                    "message_context": message_context,
                    "sender_name": message_context.sender_name,
                    "reply_target": message_context.reply_target,
                    "adapter_capabilities": message_context.capabilities,
                    "match": item.match,
                },
            )
        finally:
            reset_current_message_context(context_token)

    @staticmethod
    def _message_context(item: LocalCommandMatch, event: LocalCommandEvent) -> MessageContext:
        """生成本地驱动器的显式消息上下文。"""

        reply_target = ReplyTarget(
            adapter="local",
            client_id=event.client_id,
            conversation_type=event.conversation_type,
            driver_target=event,
        )
        return MessageContext(
            adapter="local",
            client_id=event.client_id,
            command=item.command,
            message=item.message,
            raw_message=event.raw_message,
            conversation_type=event.conversation_type,
            reply_target=reply_target,
            capabilities=LocalEventHandler.CAPABILITIES,
            identity=local_message_identity(event, tenant_id=config.project.id),
            driver_context=event,
            sender_name=event.sender_name,
        )

    @staticmethod
    def _build_command_index() -> None:
        """整理命令索引和排序。"""

        LocalEventHandler.regex_prefix_lengths = {
            len(prefix)
            for prefix in LocalEventHandler.regex_rules
        }

        for rules in LocalEventHandler.exact_rules.values():
            rules.sort(key=lambda rule: (-rule.priority, rule.order))
        for rules in LocalEventHandler.regex_rules.values():
            rules.sort(key=lambda rule: (-rule.priority, rule.order))
        LocalEventHandler.regex_fallback.sort(key=lambda rule: (-rule.priority, rule.order))

    @staticmethod
    def _split_command(raw_message: str) -> Tuple[str, str]:
        """按第一个空格拆出命令片段和业务参数文本。"""

        command, separator, message = raw_message.partition(" ")
        if not separator:
            return raw_message, ""
        return command, message.strip()

    @staticmethod
    def _message_after_match(
        clean_message: str,
        split_message: str,
        match: Optional[re.Match],
    ) -> str:
        """计算正则命令命中片段之后留给业务的文本。"""

        if match is None:
            return split_message
        return clean_message[match.end() :].lstrip()

    @staticmethod
    def _register_exact_command(
        cmd: str,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册精确命令。"""

        rule = LocalEventHandler._make_rule(func=func, priority=priority, block=block, metadata=metadata)
        LocalEventHandler.exact_rules.setdefault(cmd, []).append(rule)

    @staticmethod
    def _register_regex_command(
        pattern: Pattern,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册正则命令，并尝试按固定前缀建立候选索引。"""

        prefix = LocalEventHandler._extract_literal_prefix(pattern.pattern)
        rule = LocalEventHandler._make_rule(
            func=func,
            priority=priority,
            block=block,
            pattern=pattern,
            metadata=metadata,
        )
        if prefix:
            LocalEventHandler.regex_rules.setdefault(prefix.casefold(), []).append(rule)
        else:
            LocalEventHandler.regex_fallback.append(rule)

    @staticmethod
    def _make_rule(
        func: Callable,
        priority: int,
        block: bool,
        pattern: Optional[Pattern] = None,
        metadata: dict[str, Any] | None = None,
    ) -> LocalCommandRule:
        """创建命令规则，并记录注册顺序。"""

        order = LocalEventHandler._register_order
        LocalEventHandler._register_order += 1
        return LocalCommandRule(
            func=func,
            priority=priority,
            block=block,
            order=order,
            pattern=pattern,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    async def _match_regex_command(cmd: str) -> list[tuple[LocalCommandRule, re.Match]]:
        """匹配正则命令。"""

        matched = []
        key = cmd.casefold()
        seen_rules: Set[int] = set()

        for length in LocalEventHandler.regex_prefix_lengths:
            if length > len(key):
                continue

            for start in range(0, len(key) - length + 1):
                for rule in LocalEventHandler.regex_rules.get(key[start : start + length], []):
                    rule_id = id(rule)
                    if rule_id in seen_rules:
                        continue

                    seen_rules.add(rule_id)
                    match = rule.pattern.search(cmd) if rule.pattern is not None else None
                    if match:
                        matched.append((rule, match))

        for rule in LocalEventHandler.regex_fallback:
            rule_id = id(rule)
            if rule_id in seen_rules:
                continue

            seen_rules.add(rule_id)
            match = rule.pattern.search(cmd) if rule.pattern is not None else None
            if match:
                matched.append((rule, match))

        return matched

    @staticmethod
    def _extract_literal_prefix(source: str) -> str:
        """从正则源码中提取开头固定文字。"""

        index = 1 if source.startswith("^") else 0
        prefix = []
        metacharacters = set(".^$*+?{}[]|()")

        while index < len(source):
            char = source[index]

            if char in metacharacters:
                break

            if char == "\\":
                if index + 1 >= len(source):
                    break

                next_char = source[index + 1]
                if next_char in "AbBdDsSwWZ0123456789":
                    break

                prefix.append(next_char)
                index += 2
                continue

            prefix.append(char)
            index += 1

        return "".join(prefix)

    @staticmethod
    def _normalize_commands(value) -> list:
        """把单个 cmd 或多个 cmd 统一成 list。"""

        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    @staticmethod
    def _short_text(value: object, limit: int = 80) -> str:
        """压缩日志正文长度。"""

        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return "-"
        if len(text) <= limit:
            return text
        return f"{text[:limit - 1]}..."
