"""游戏命令的访问与人物行为状态守卫。"""

from __future__ import annotations

from game.app import current_game_services
from game.core.activity import ActivityRuleError
from launch.adapter import (
    CommandGuardContext,
    CommandGuardDecision,
    register_command_guard,
)
from message import M

from .command import GAME_METADATA_KEY

GAME_GUARD_NAME = "game.access"
GAME_GUARD_PRIORITY = 1000


async def game_access_guard(context: CommandGuardContext) -> CommandGuardDecision:
    metadata = context.command_metadata.get(GAME_METADATA_KEY)
    if not isinstance(metadata, dict):
        return CommandGuardDecision.allow()
    rule_name = str(metadata.get("activity_rule") or "").strip()
    if not rule_name:
        return CommandGuardDecision.allow()
    user_id = context.message_context.identity.primary.external_id
    try:
        result = await current_game_services().core.activity.authorize(user_id, rule_name)
    except ActivityRuleError as exc:
        return CommandGuardDecision.block(reason=str(exc))
    if result.allowed:
        return CommandGuardDecision.allow()
    return CommandGuardDecision.block(
        M.document().section("当前状态").line(result.reason).build(),
        reason=result.reason,
    )


register_command_guard(GAME_GUARD_NAME, game_access_guard, priority=GAME_GUARD_PRIORITY)


__all__ = ["GAME_GUARD_NAME", "GAME_GUARD_PRIORITY", "game_access_guard"]
