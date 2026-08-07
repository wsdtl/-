from __future__ import annotations

from types import SimpleNamespace

import pytest

import game.app as game_app
from game.cmd import access_guard, command


class _FakeDatabase:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _BrokenPlayerState:
    def validate_guard_rule(self, rule_name: str) -> None:
        raise RuntimeError(f"未知规则：{rule_name}")


def test_failed_guard_validation_releases_built_services(monkeypatch) -> None:
    database = _FakeDatabase()
    services = SimpleNamespace(
        core=SimpleNamespace(
            database=database,
            player_state=_BrokenPlayerState(),
        )
    )
    monkeypatch.setattr(game_app, "_services", None)
    monkeypatch.setattr(game_app, "build_game_services", lambda: services)
    monkeypatch.setattr(command, "registered_guard_rules", lambda: ("不存在",))
    monkeypatch.setattr(access_guard, "unregister_game_access_guard", lambda: None)

    with pytest.raises(RuntimeError, match="未知规则"):
        game_app.initialize_game_services()

    assert database.closed is True
    assert game_app._services is None
