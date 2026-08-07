"""游戏命令的玩家状态守卫。"""

from __future__ import annotations

from game.app import current_game_services
from launch.adapter import (
    CommandGuardContext,
    CommandGuardDecision,
    register_command_guard,
    unregister_command_guard,
)
from message import M

from .command import GAME_METADATA_KEY

GAME_GUARD_NAME = "game.player_state"
GAME_GUARD_PRIORITY = 1000


async def game_access_guard(context: CommandGuardContext) -> CommandGuardDecision:
    metadata = context.command_metadata.get(GAME_METADATA_KEY)
    if not isinstance(metadata, dict):
        return CommandGuardDecision.allow()
    rule_name = str(metadata.get("guard_rule") or "").strip()
    if not rule_name:
        reason = "游戏命令缺少状态守卫规则"
        return CommandGuardDecision.block(_blocked_message(reason), reason=reason)
    user_id = context.message_context.user_id
    try:
        result = await current_game_services().core.player_state.authorize(
            user_id, rule_name
        )
    except Exception:  # noqa: BLE001 - guard failures must fail closed
        reason = "状态检查失败，请稍后重试"
        return CommandGuardDecision.block(_blocked_message(reason), reason=reason)
    if result.allowed:
        return CommandGuardDecision.allow()
    return CommandGuardDecision.block(
        _blocked_message(result.reason),
        reason=result.reason,
    )


def register_game_access_guard() -> None:
    """由游戏组合根显式注册守卫。"""

    register_command_guard(
        GAME_GUARD_NAME, game_access_guard, priority=GAME_GUARD_PRIORITY
    )


def unregister_game_access_guard() -> None:
    """随游戏微服务关闭移除守卫。"""

    unregister_command_guard(GAME_GUARD_NAME)


def _blocked_message(reason: str):
    return M.document().section("当前状态").line(reason).build()


__all__ = [
    "GAME_GUARD_NAME",
    "GAME_GUARD_PRIORITY",
    "game_access_guard",
    "register_game_access_guard",
    "unregister_game_access_guard",
]
