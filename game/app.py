"""数据库、按需文件读取和当前玩法组件的装配入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from launch import OnEvent, config

from .content import GameContent
from .core import Database, JsonDataReader, utc_now
from .features import (
    EnemyFeature,
    ExplorationFeature,
    LocationFeature,
    NpcFeature,
    PlayerFeature,
    SeclusionFeature,
)
from .rules import BattleEngine


@dataclass(frozen=True)
class GameServices:
    data: JsonDataReader
    content: GameContent
    database: Database
    player: PlayerFeature
    location: LocationFeature
    npc: NpcFeature
    enemy: EnemyFeature
    battle: BattleEngine
    seclusion: SeclusionFeature
    exploration: ExplorationFeature


def build_game_services(
    *,
    data_dir: str | Path | None = None,
    database_path: str | Path | None = None,
    busy_timeout_ms: int | None = None,
    clock: Callable[[], str] = utc_now,
) -> GameServices:
    data = JsonDataReader(data_dir or (config.base_dir / "data"))
    content = GameContent.load(data)
    database = Database(
        database_path or config.database.path,
        busy_timeout_ms=(
            busy_timeout_ms
            if busy_timeout_ms is not None
            else config.database.busy_timeout_ms
        ),
    )
    player = PlayerFeature(database, content)
    location = LocationFeature(database, content, player, clock=clock)
    npc = NpcFeature(content, location)
    enemy = EnemyFeature(content)
    battle = BattleEngine(content.combat)
    seclusion = SeclusionFeature(database, content, player, location, clock=clock)
    exploration = ExplorationFeature(
        database,
        content,
        player,
        location,
        enemy,
        battle,
        clock=clock,
    )
    player.initialize()
    location.initialize()
    seclusion.initialize()
    exploration.initialize()
    return GameServices(
        data=data,
        content=content,
        database=database,
        player=player,
        location=location,
        npc=npc,
        enemy=enemy,
        battle=battle,
        seclusion=seclusion,
        exploration=exploration,
    )


_services: GameServices | None = None


def current_game_services() -> GameServices:
    global _services
    if _services is None:
        _services = build_game_services()
    return _services


@OnEvent.connect(priority=200)
def initialize_game_services() -> None:
    current_game_services()


__all__ = [
    "GameServices",
    "build_game_services",
    "current_game_services",
    "initialize_game_services",
]
