from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from game.cmd import access_guard
from game.cmd.command import GameCommand, HelpSpec
from game.cmd.help_registry import help_registry
from game.core.activity import ActivityAccessResult
from launch.adapter import (
    AdapterCapabilities,
    CommandGuardContext,
    MessageContext,
    MessageIdentity,
    MessageIdentityClaim,
    ReplyTarget,
)
from launch.adapter.local import LocalEventHandler, dispatch
from main import create_app


def _run(awaitable):
    return asyncio.run(awaitable)


def _content(result) -> str:
    assert result.matched
    assert len(result.replies) == 1
    return result.replies[0].message.content


def test_help_registry_is_built_from_loaded_commands() -> None:
    create_app()

    assert help_registry.categories() == ("角色",)
    assert [entry.command for entry in help_registry.entries()] == ["帮助", "创建人物"]
    assert help_registry.find("web") is None


def test_game_command_requires_help_or_hidden() -> None:
    with pytest.raises(ValueError, match="必须提供"):
        GameCommand.fullmatch("缺少说明")
    with pytest.raises(ValueError, match="不能同时"):
        GameCommand.fullmatch(
            "重复声明",
            help=HelpSpec("角色", "测试命令", ("重复声明",)),
            hidden=True,
        )


def test_help_home_and_detail_use_real_registered_commands() -> None:
    create_app()
    _run(LocalEventHandler.run())

    home = _run(
        dispatch(
            client_id="help-user",
            raw_message="帮助",
            sender_name="问路人",
            event_id="help-home",
        )
    )
    assert "按分类查看当前已经开放的命令" in _content(home)
    assert "角色" in _content(home)

    detail = _run(
        dispatch(
            client_id="help-user",
            raw_message="帮助 创建人物",
            sender_name="问路人",
            event_id="help-detail",
        )
    )
    assert "建立当前账号的唯一修士人物" in _content(detail)
    assert "创建人物 姓名 性别" in _content(detail)
    assert tuple(action.data for action in detail.replies[0].message.actions) == (
        "创建人物",
        "帮助 角色",
    )


def test_public_command_still_obeys_activity_rule(monkeypatch) -> None:
    class FakeActivity:
        async def authorize(self, user_id: str, rule_name: str) -> ActivityAccessResult:
            assert user_id == "help-user"
            assert rule_name == "仅未创建"
            return ActivityAccessResult(False, "已经创建人物")

    identity = MessageIdentity(
        evidence_id="help-guard",
        source_kind="test",
        primary=MessageIdentityClaim(
            "test",
            "test",
            "user",
            "",
            "help-user",
        ),
    )
    context = CommandGuardContext(
        message_context=MessageContext(
            adapter="local",
            client_id="help-user",
            command="创建人物",
            message="林远 男",
            raw_message="创建人物 林远 男",
            conversation_type="private",
            reply_target=ReplyTarget("local", "help-user", "private"),
            capabilities=AdapterCapabilities(),
            identity=identity,
        ),
        command_metadata={"game": {"access": "public", "activity_rule": "仅未创建"}},
    )
    monkeypatch.setattr(
        access_guard,
        "current_game_services",
        lambda: SimpleNamespace(core=SimpleNamespace(activity=FakeActivity())),
    )

    decision = _run(access_guard.game_access_guard(context))
    assert decision.blocked is True
