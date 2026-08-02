"""新框架地基的生命周期、守卫和 QQ 匹配回归测试。"""

from __future__ import annotations

import asyncio
import re
from importlib import import_module
from types import SimpleNamespace

import pytest

import game.app as game_app
import launch.adapter.local.handler as local_handler_module
import launch.adapter.qq.handler as qq_handler_module
from game.config import load_game_config
from launch.adapter.command_guard import CommandGuardDecision
from launch.adapter.context import (
    AdapterCapabilities,
    MessageContext,
    MessageIdentity,
    MessageIdentityClaim,
    ReplyTarget,
)
from launch.adapter.local.event import local_command_event
from launch.adapter.local.handler import (
    LocalCommandMatch,
    LocalCommandRule,
    LocalEventHandler,
)
from launch.adapter.qq.event import QqMessageEvent
from launch.adapter.qq.handler import QqEventHandler
from launch.adapter.qq.rules import (
    QqCommandMatch,
    QqCommandRegistry,
    QqCommandRule,
)
from launch.config import Config
from launch.on_event import EventCallback, OnEvent

lifespan_module = import_module("launch.lifespan")


def test_game_services_can_only_be_built_by_startup(monkeypatch) -> None:
    services = object()
    monkeypatch.setattr(game_app, "_services", None)
    monkeypatch.setattr(game_app, "build_game_services", lambda: services)

    with pytest.raises(RuntimeError, match="尚未初始化"):
        game_app.current_game_services()

    game_app.initialize_game_services()
    assert game_app.current_game_services() is services
    with pytest.raises(RuntimeError, match="已经初始化"):
        game_app.initialize_game_services()
    game_app.shutdown_game_services()
    with pytest.raises(RuntimeError, match="尚未初始化"):
        game_app.current_game_services()


def test_legacy_runtime_storage_moves_out_of_data(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "game.db").write_bytes(b"game")
    (data_dir / "runtime_log.db").write_bytes(b"log")
    backups = data_dir / "backups"
    backups.mkdir()
    (backups / "snapshot.db").write_bytes(b"backup")
    media = data_dir / "runtime_log_media"
    media.mkdir()
    (media / "image.png").write_bytes(b"image")
    runtime = tmp_path / ".runtime"
    monkeypatch.setattr(
        game_app,
        "config",
        SimpleNamespace(base_dir=tmp_path),
    )
    monkeypatch.setattr(
        game_app,
        "game_config",
        SimpleNamespace(
            database=SimpleNamespace(
                path=runtime / "game.db",
                runtime_log_path=runtime / "runtime_log.db",
            ),
        ),
    )
    monkeypatch.setattr(
        game_app,
        "logger",
        SimpleNamespace(
            opt=lambda **_kwargs: SimpleNamespace(info=lambda *_args, **_kwargs: None)
        ),
    )

    game_app.migrate_legacy_runtime_storage()

    assert not (data_dir / "game.db").exists()
    assert not (data_dir / "runtime_log.db").exists()
    assert not backups.exists()
    assert not media.exists()
    assert (runtime / "game.db").read_bytes() == b"game"
    assert (runtime / "runtime_log.db").read_bytes() == b"log"
    assert (runtime / "backups" / "snapshot.db").read_bytes() == b"backup"
    assert (runtime / "runtime_log_media" / "image.png").read_bytes() == b"image"


def test_game_database_settings_use_framework_custom_values(tmp_path) -> None:
    values = {
        "DATABASE_PATH": "state/game.sqlite",
        "RUNTIME_LOG_DATABASE_PATH": "state/runtime.sqlite",
        "DATABASE_BUSY_TIMEOUT_MS": "2300",
    }
    source = SimpleNamespace(
        base_dir=tmp_path,
        get=lambda name, default="": values.get(name, default),
    )

    settings = load_game_config(source)

    assert settings.database.path == tmp_path / "state" / "game.sqlite"
    assert settings.database.runtime_log_path == tmp_path / "state" / "runtime.sqlite"
    assert settings.database.busy_timeout_ms == 2300


def test_framework_config_does_not_own_game_database_settings() -> None:
    assert "database" not in Config.__dataclass_fields__


def test_local_guards_preflight_every_planned_callback(monkeypatch) -> None:
    checked: list[str] = []

    async def guard(context):
        permission = context.command_metadata["permission"]
        checked.append(permission)
        if permission == "denied":
            return CommandGuardDecision.block()
        return CommandGuardDecision.allow()

    monkeypatch.setattr(local_handler_module, "run_command_guards", guard)
    event = local_command_event(client_id="local-user", raw_message="测试")
    matches = [
        _local_match(order=0, permission="allowed"),
        _local_match(order=1, permission="denied"),
    ]

    blocked = asyncio.run(LocalEventHandler._guards_blocked(matches, event))

    assert blocked is True
    assert checked == ["allowed", "denied"]


def test_qq_guards_preflight_every_planned_callback(monkeypatch) -> None:
    checked: list[str] = []

    async def guard(context):
        permission = context.command_metadata["permission"]
        checked.append(permission)
        if permission == "denied":
            return CommandGuardDecision.block()
        return CommandGuardDecision.allow()

    monkeypatch.setattr(qq_handler_module, "run_command_guards", guard)
    monkeypatch.setattr(
        QqEventHandler,
        "_message_context",
        staticmethod(lambda item, event: _message_context("qq", event.client_id)),
    )
    event = QqMessageEvent(
        event_type="C2C_MESSAGE_CREATE",
        event_id="event-1",
        message_id="message-1",
        client_id="qq-user",
        content="测试",
        group_openid="",
        actor_openid="qq-user",
        user_openid="qq-user",
        member_openid="",
        raw={},
    )
    matches = [
        _qq_match(order=0, permission="allowed"),
        _qq_match(order=1, permission="denied"),
    ]

    blocked = asyncio.run(QqEventHandler._guards_blocked(matches, event))

    assert blocked is True
    assert checked == ["allowed", "denied"]


def test_qq_registry_keeps_three_matching_modes_distinct() -> None:
    registry = QqCommandRegistry()

    async def callback():
        return None

    registry.register_fullmatch("web", callback, 0, False)
    registry.register_command("go", callback, 0, False)
    registry.register_regex(re.compile(r"赠予\s+\S+\s+\d+"), callback, 0, False)
    registry.build_index()

    assert [item.command for item in registry.match("web")] == ["web"]
    assert registry.match("web bb") == []
    go_match = registry.match("go 青溪村")
    assert [(item.command, item.message) for item in go_match] == [("go", "青溪村")]
    assert len(registry.match("赠予 灵石 3")) == 1
    assert registry.match("赠予 灵石") == []


def test_lifespan_rolls_back_every_started_phase(monkeypatch) -> None:
    trace: list[str] = []

    class Adapter:
        @staticmethod
        async def run() -> None:
            trace.append("adapter.run")

        @staticmethod
        async def shutdown() -> None:
            trace.append("adapter.shutdown")

    async def mount(_app):
        return [Adapter]

    async def start_schedulers():
        trace.append("schedulers.start")

    async def add_jobs():
        trace.append("schedulers.add_jobs")

    async def stop_schedulers():
        trace.append("schedulers.shutdown")

    def connect() -> None:
        trace.append("service.connect")
        raise RuntimeError("connect failed")

    def disconnect() -> None:
        trace.append("service.disconnect")

    monkeypatch.setattr(lifespan_module, "_mount_app", mount)
    monkeypatch.setattr(lifespan_module, "_start_schedulers", start_schedulers)
    monkeypatch.setattr(lifespan_module, "_add_scheduler_jobs", add_jobs)
    monkeypatch.setattr(lifespan_module, "_shutdown_schedulers", stop_schedulers)
    monkeypatch.setattr(
        lifespan_module.runtime_guard,
        "acquire",
        lambda: trace.append("guard.acquire"),
    )
    monkeypatch.setattr(
        lifespan_module.runtime_guard,
        "release",
        lambda: trace.append("guard.release"),
    )
    monkeypatch.setattr(
        OnEvent,
        "connect_list",
        [EventCallback(priority=0, order=0, func=connect)],
    )
    monkeypatch.setattr(
        OnEvent,
        "disconnect_list",
        [EventCallback(priority=0, order=1, func=disconnect)],
    )

    async def run() -> None:
        with pytest.raises(RuntimeError, match="connect failed"):
            async with lifespan_module.lifespan(object()):
                pytest.fail("启动失败后不应进入服务阶段")

    asyncio.run(run())

    assert trace == [
        "guard.acquire",
        "adapter.run",
        "schedulers.start",
        "schedulers.add_jobs",
        "service.connect",
        "service.disconnect",
        "schedulers.shutdown",
        "adapter.shutdown",
        "guard.release",
    ]


def _local_match(*, order: int, permission: str) -> LocalCommandMatch:
    return LocalCommandMatch(
        rule=LocalCommandRule(
            func=lambda: None,
            priority=0,
            block=False,
            order=order,
            metadata={"permission": permission},
        ),
        command="测试",
        message="",
    )


def _qq_match(*, order: int, permission: str) -> QqCommandMatch:
    return QqCommandMatch(
        rule=QqCommandRule(
            func=lambda: None,
            priority=0,
            block=False,
            order=order,
            metadata={"permission": permission},
        ),
        command="测试",
        message="",
    )


def _message_context(adapter: str, client_id: str) -> MessageContext:
    claim = MessageIdentityClaim(
        provider_id=f"platform.{adapter}",
        tenant_id="test",
        subject_kind="identity.test",
        scope_id="",
        external_id=client_id,
    )
    return MessageContext(
        adapter=adapter,
        client_id=client_id,
        command="测试",
        message="",
        raw_message="测试",
        conversation_type="private",
        reply_target=ReplyTarget(adapter, client_id, "private"),
        capabilities=AdapterCapabilities(),
        identity=MessageIdentity("test-event", "identity.test", claim),
    )
