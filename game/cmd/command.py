"""游戏命令统一注册入口。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from launch.adapter import MessageHandler

from .help_registry import HelpSpec, help_registry

GAME_METADATA_KEY = "game"
GAME_ACCESS_PUBLIC = "public"
GAME_ACCESS_PLAYER = "player"
GAME_ACCESS_VALUES = frozenset({GAME_ACCESS_PUBLIC, GAME_ACCESS_PLAYER})
DEFAULT_ACTIVITY_RULE = "仅空闲"


class GameCommand:
    """给三种底层注册器补齐访问、状态和帮助契约。"""

    @staticmethod
    def fullmatch(
        cmd,
        *,
        access: str = GAME_ACCESS_PLAYER,
        activity_rule: str | None = DEFAULT_ACTIVITY_RULE,
        help: HelpSpec | None = None,
        hidden: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        block: bool = True,
    ) -> Callable:
        return _register(
            MessageHandler.fullmatch,
            cmd,
            access=access,
            activity_rule=activity_rule,
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
        access: str = GAME_ACCESS_PLAYER,
        activity_rule: str | None = DEFAULT_ACTIVITY_RULE,
        help: HelpSpec | None = None,
        hidden: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        block: bool = True,
    ) -> Callable:
        return _register(
            MessageHandler.command,
            cmd,
            access=access,
            activity_rule=activity_rule,
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
        access: str = GAME_ACCESS_PLAYER,
        activity_rule: str | None = DEFAULT_ACTIVITY_RULE,
        help: HelpSpec | None = None,
        hidden: bool = False,
        metadata: dict[str, Any] | None = None,
        priority: int = 100,
        block: bool = True,
    ) -> Callable:
        return _register(
            MessageHandler.regex,
            cmd,
            access=access,
            activity_rule=activity_rule,
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
    access: str,
    activity_rule: str | None,
    help: HelpSpec | None,
    hidden: bool,
    metadata: dict[str, Any] | None,
    priority: int,
    block: bool,
) -> Callable:
    normalized_access = str(access or "").strip().lower()
    if normalized_access not in GAME_ACCESS_VALUES:
        raise ValueError(f"未知游戏命令访问级别：{access}")
    if help is not None and hidden:
        raise ValueError("游戏命令不能同时登记帮助并标记为隐藏")
    if help is None and not hidden:
        raise ValueError("游戏命令必须提供 help=HelpSpec(...) 或 hidden=True")
    if activity_rule is not None and not str(activity_rule).strip():
        raise ValueError("人物状态准入规则不能为空")

    merged = dict(metadata or {})
    game_metadata = dict(merged.get(GAME_METADATA_KEY) or {})
    game_metadata["access"] = normalized_access
    if activity_rule is not None:
        game_metadata["activity_rule"] = str(activity_rule).strip()
    merged[GAME_METADATA_KEY] = game_metadata
    if help is not None:
        help_registry.register(cmd, help, access=normalized_access)
    return registrar(cmd=cmd, priority=priority, block=block, metadata=merged)


__all__ = [
    "DEFAULT_ACTIVITY_RULE",
    "GAME_ACCESS_PLAYER",
    "GAME_ACCESS_PUBLIC",
    "GAME_METADATA_KEY",
    "GameCommand",
    "HelpSpec",
]
