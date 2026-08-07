from __future__ import annotations

import asyncio
from inspect import signature

from launch.adapter import (
    AdapterCapabilities,
    CommandGuardContext,
    MessageContext,
    ReplyTarget,
    clear_command_guards,
    register_command_guard,
    run_command_guards,
)
from launch.adapter.local import LocalCommandEvent, LocalEventHandler


def _run(awaitable):
    return asyncio.run(awaitable)


def _context() -> CommandGuardContext:
    return CommandGuardContext(
        message_context=MessageContext(
            adapter="local",
            user_id="qq-1",
            request_id="event-1",
            command="测试",
            message="",
            raw_message="测试",
            conversation_type="private",
            reply_target=ReplyTarget("local", "qq-1", "qq-1", "private"),
            capabilities=AdapterCapabilities(),
        )
    )


def test_invalid_guard_result_fails_closed_with_visible_reply() -> None:
    clear_command_guards()

    def invalid_guard(_):
        return None

    register_command_guard("invalid", invalid_guard)
    decision = _run(run_command_guards(_context()))
    clear_command_guards()

    assert decision.blocked is True
    assert decision.reply
    assert "无效结果" in decision.reason


def test_guard_exception_fails_closed_with_visible_reply() -> None:
    clear_command_guards()

    def broken_guard(_):
        raise RuntimeError("broken")

    register_command_guard("broken", broken_guard)
    decision = _run(run_command_guards(_context()))
    clear_command_guards()

    assert decision.blocked is True
    assert decision.reply
    assert "broken" in decision.reason


def test_normal_local_dispatch_has_no_guard_bypass_parameter() -> None:
    assert "bypass_guards" not in signature(LocalCommandEvent).parameters
    assert "bypass_guards" not in signature(LocalEventHandler.dispatch).parameters
