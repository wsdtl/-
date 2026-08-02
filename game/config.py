"""从框架自定义项中解释游戏自身配置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from launch import config as framework_config


class CustomConfigSource(Protocol):
    """游戏配置只依赖框架公开的自定义项读取能力。"""

    base_dir: Path

    def get(self, name: str, default: str = "") -> str: ...


@dataclass(frozen=True)
class GameDatabaseConfig:
    path: Path
    runtime_log_path: Path
    busy_timeout_ms: int


@dataclass(frozen=True)
class GameConfig:
    database: GameDatabaseConfig


def load_game_config(source: CustomConfigSource = framework_config) -> GameConfig:
    """读取并校验游戏自定义配置，不向框架注册业务字段。"""

    database = GameDatabaseConfig(
        path=_custom_path(source, "DATABASE_PATH", "database/game.db"),
        runtime_log_path=_custom_path(
            source,
            "RUNTIME_LOG_DATABASE_PATH",
            "database/runtime_log.db",
        ),
        busy_timeout_ms=_positive_int(source, "DATABASE_BUSY_TIMEOUT_MS", 5000),
    )
    return GameConfig(database=database)


def _custom_path(source: CustomConfigSource, name: str, default: str) -> Path:
    raw = (source.get(name, default) or default).strip()
    path = Path(raw).expanduser()
    return path if path.is_absolute() else source.base_dir / path


def _positive_int(source: CustomConfigSource, name: str, default: int) -> int:
    raw = (source.get(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if value < 1:
        raise ValueError(f"{name} 必须大于 0")
    return value


game_config = load_game_config()


__all__ = [
    "GameConfig",
    "GameDatabaseConfig",
    "game_config",
    "load_game_config",
]
