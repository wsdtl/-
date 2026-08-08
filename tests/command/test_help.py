from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.cmd import access_guard
from game.cmd.command import GameCommand, HelpSpec
from game.cmd.help_registry import help_registry
from game.core.data import JsonDataService
from game.core.item_catalog import ItemCatalogService
from game.core.player_state import StateGuardResult
from game.features.chakan_wupin import ItemInspectionFeature
from launch.adapter import (
    AdapterCapabilities,
    CommandGuardContext,
    MessageContext,
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


def test_loaded_commands_have_one_valid_help_declaration() -> None:
    create_app()

    assert help_registry.categories() == ("角色", "行动", "世界", "资源")
    assert [entry.command for entry in help_registry.entries()] == [
        "帮助",
        "创建人物",
        "人物",
        "去",
        "地图",
        "位置",
        "附近",
        "纳戒",
        "查看物品",
    ]
    assert help_registry.find("web") is None
    assert help_registry.find("天道后台") is None
    with pytest.raises(TypeError):
        GameCommand.fullmatch("缺少说明")
    with pytest.raises(ValueError, match="不能同时"):
        GameCommand.fullmatch(
            "重复声明",
            guard_rule="始终可用",
            help=HelpSpec("角色", "测试命令", ("重复声明",)),
            hidden=True,
        )


def test_help_home_and_detail_use_real_registered_commands(monkeypatch) -> None:
    create_app()
    _run(LocalEventHandler.run())

    home = _run(
        dispatch(
            user_id="help-user",
            raw_message="帮助",
            sender_name="问路人",
            event_id="help-home",
        )
    )
    assert "按分类查看当前已经开放的命令" in _content(home)
    assert "角色" in _content(home)

    detail = _run(
        dispatch(
            user_id="help-user",
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

    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    catalog = ItemCatalogService(data)
    catalog.initialize()
    feature = ItemInspectionFeature(catalog)
    feature.initialize()
    inspect_module = import_module("game.cmd.查看")
    monkeypatch.setattr(
        inspect_module,
        "current_game_services",
        lambda: SimpleNamespace(features=SimpleNamespace(chakan_wupin=feature)),
    )
    item = _run(
        dispatch(
            user_id="help-user",
            raw_message="查看物品 小还丹",
            sender_name="问路人",
            event_id="inspect-item",
        )
    )
    item_content = _content(item)
    assert "小还丹" in item_content
    assert "丹药" in item_content
    assert "100005" in item_content
    assert "恢复百分比：15" in item_content
    assert "权重" not in item_content
    assert "参考价" not in item_content


def test_game_command_guard_uses_player_state_rule(monkeypatch) -> None:
    class FakePlayerState:
        async def authorize(self, user_id: str, rule_name: str) -> StateGuardResult:
            assert user_id == "help-user"
            assert rule_name == "仅未创建"
            return StateGuardResult(False, "已经创建人物")

    context = CommandGuardContext(
        message_context=MessageContext(
            adapter="local",
            user_id="help-user",
            request_id="help-guard",
            command="创建人物",
            message="林远 男",
            raw_message="创建人物 林远 男",
            conversation_type="private",
            reply_target=ReplyTarget("local", "help-user", "help-user", "private"),
            capabilities=AdapterCapabilities(),
        ),
        command_metadata={"game": {"guard_rule": "仅未创建"}},
    )
    monkeypatch.setattr(
        access_guard,
        "current_game_services",
        lambda: SimpleNamespace(core=SimpleNamespace(player_state=FakePlayerState())),
    )

    decision = _run(access_guard.game_access_guard(context))
    assert decision.blocked is True
