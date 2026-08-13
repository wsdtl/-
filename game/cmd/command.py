"""游戏命令统一注册入口。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from launch.adapter import MessageHandler

from .help_registry import HelpSpec, help_registry

GAME_METADATA_KEY = "game"
COMMAND_SCOPES = frozenset({"通用", "专属", "后台"})
_registered_guard_rules: set[str] = set()
_registered_commands: list[tuple[str, str, str]] = []


class GameCommand:
    """给三种底层注册器补齐状态守卫和帮助契约。"""

    @staticmethod
    def fullmatch(
        cmd,
        *,
        scope: str,
        guard_rule: str,
        help: HelpSpec | None = None,
        hidden: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        block: bool = True,
    ) -> Callable:
        return _register(
            MessageHandler.fullmatch,
            cmd,
            scope=scope,
            guard_rule=guard_rule,
            help=help,
            hidden=hidden,
            metadata=metadata,
            priority=priority,
            block=block,
        )

    @staticmethod
    def command(
        cmd,
        *,
        scope: str,
        guard_rule: str,
        help: HelpSpec | None = None,
        hidden: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        block: bool = True,
    ) -> Callable:
        return _register(
            MessageHandler.command,
            cmd,
            scope=scope,
            guard_rule=guard_rule,
            help=help,
            hidden=hidden,
            metadata=metadata,
            priority=priority,
            block=block,
        )

    @staticmethod
    def regex(
        cmd,
        *,
        scope: str,
        guard_rule: str,
        help: HelpSpec | None = None,
        hidden: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        block: bool = True,
    ) -> Callable:
        return _register(
            MessageHandler.regex,
            cmd,
            scope=scope,
            guard_rule=guard_rule,
            help=help,
            hidden=hidden,
            metadata=metadata,
            priority=priority,
            block=block,
        )


def _register(
    registrar: Callable[..., Callable],
    cmd,
    *,
    scope: str,
    guard_rule: str,
    help: HelpSpec | None,
    hidden: bool,
    metadata: dict[str, Any] | None,
    priority: int,
    block: bool,
) -> Callable:
    normalized_scope = str(scope or "").strip()
    if normalized_scope not in COMMAND_SCOPES:
        raise ValueError(f"游戏命令 scope 必须是：{'、'.join(sorted(COMMAND_SCOPES))}")
    normalized_guard_rule = str(guard_rule or "").strip()
    if not normalized_guard_rule:
        raise ValueError("游戏命令必须显式声明状态守卫规则")
    if help is not None and hidden:
        raise ValueError("游戏命令不能同时登记帮助并标记为隐藏")
    if help is None and not hidden:
        raise ValueError("游戏命令必须提供 help=HelpSpec(...) 或 hidden=True")
    merged = dict(metadata or {})
    game_metadata = dict(merged.get(GAME_METADATA_KEY) or {})
    game_metadata["guard_rule"] = normalized_guard_rule
    game_metadata["scope"] = normalized_scope
    merged[GAME_METADATA_KEY] = game_metadata
    _registered_guard_rules.add(normalized_guard_rule)
    if help is not None:
        help_registry.register(cmd, help)
    register = registrar(cmd=cmd, priority=priority, block=block, metadata=merged)

    def decorate(func: Callable) -> Callable:
        decorated = register(func)
        _registered_commands.append((str(cmd), normalized_scope, func.__module__))
        return decorated

    return decorate


def registered_guard_rules() -> tuple[str, ...]:
    """返回所有已加载游戏命令显式引用的守卫规则。"""

    return tuple(sorted(_registered_guard_rules))


def registered_commands() -> tuple[tuple[str, str, str], ...]:
    """返回命令、声明范围和来源模块，供启动审查器使用。"""

    return tuple(_registered_commands)


__all__ = [
    "COMMAND_SCOPES",
    "GAME_METADATA_KEY",
    "GameCommand",
    "HelpSpec",
    "registered_commands",
    "registered_guard_rules",
]
