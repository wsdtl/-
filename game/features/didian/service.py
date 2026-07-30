"""单世界地点坐标、人物位置与即时移动。"""

from __future__ import annotations

from collections.abc import Callable
import sqlite3

from game.content import GameContent
from game.core import Database, record_exists, require_user_id, utc_now
from game.features.player import PlayerFeature

from .models import LocationState, LocationSummary, MoveResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS player_locations (
    user_id TEXT PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    z INTEGER NOT NULL DEFAULT 0,
    arrived_at TEXT NOT NULL
);
"""

MOVED = "moved"
ALREADY_THERE = "already_there"
NOT_FOUND = "not_found"
ACTIVITY_ACTIVE = "activity_active"


class LocationFeature:
    def __init__(
        self,
        database: Database,
        content: GameContent,
        player: PlayerFeature,
        *,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.database = database
        self.content = content
        self.player = player
        self.clock = clock
        self._coordinates_by_id = {
            str(location_id): _coordinates(definition)
            for location_id, definition in self.content.location_definitions.items()
        }
        self._ids_by_coordinates = {
            coordinates: location_id
            for location_id, coordinates in self._coordinates_by_id.items()
        }

    @property
    def world_name(self) -> str:
        return str(self.content.world_definition["名称"])

    @property
    def world_description(self) -> str:
        return str(self.content.world_definition["说明"])

    @property
    def coordinate_bounds(self) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
        bounds = self.content.world_definition["坐标边界"]
        return (
            (int(bounds["x轴"][0]), int(bounds["x轴"][1])),
            (int(bounds["y轴"][0]), int(bounds["y轴"][1])),
            (int(bounds["z轴"][0]), int(bounds["z轴"][1])),
        )

    def initialize(self) -> None:
        self.database.initialize(SCHEMA)
        with self.database.transaction(write=True) as connection:
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(player_locations)")
            }
            if "z" not in columns:
                connection.execute(
                    "ALTER TABLE player_locations ADD COLUMN z INTEGER NOT NULL DEFAULT 0"
                )

    def current(self, user_id: str, display_name: str = "") -> LocationState:
        actor = require_user_id(user_id)
        with self.database.transaction(write=True) as connection:
            self.player.ensure_in_connection(connection, actor, display_name)
            coordinates = self.ensure_in_connection(connection, actor)
        return self.state_at(*coordinates)

    def current_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
    ) -> LocationState:
        actor = require_user_id(user_id)
        return self.state_at(*self.ensure_in_connection(connection, actor))

    def ensure_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
    ) -> tuple[int, int, int]:
        actor = require_user_id(user_id)
        row = connection.execute(
            "SELECT x, y, z FROM player_locations WHERE user_id = ?",
            (actor,),
        ).fetchone()
        if row is None:
            location_id = str(self.content.world_definition["出生地"])
            x, y, z = self._coordinates_by_id[location_id]
            connection.execute(
                "INSERT INTO player_locations(user_id, x, y, z, arrived_at) VALUES (?, ?, ?, ?, ?)",
                (actor, x, y, z, self.clock()),
            )
            return x, y, z
        coordinates = int(row["x"]), int(row["y"]), int(row["z"])
        if coordinates not in self._ids_by_coordinates:
            raise RuntimeError(f"人物所在坐标没有登记地点：{coordinates}")
        return coordinates

    def move(self, user_id: str, destination_name: str, display_name: str = "") -> MoveResult:
        actor = require_user_id(user_id)
        destination_id = self.resolve_name(destination_name)
        with self.database.transaction(write=True) as connection:
            self.player.ensure_in_connection(connection, actor, display_name)
            current = self.state_at(*self.ensure_in_connection(connection, actor))
            if record_exists(connection, "seclusion_states", actor) or record_exists(
                connection,
                "exploration_states",
                actor,
            ):
                return MoveResult(ACTIVITY_ACTIVE, current)
            if destination_id is None:
                return MoveResult(NOT_FOUND, current)
            destination = self.state(destination_id)
            if destination.location_id == current.location_id:
                return MoveResult(ALREADY_THERE, current)
            distance = self.distance(current, destination)
            connection.execute(
                "UPDATE player_locations SET x = ?, y = ?, z = ?, arrived_at = ? WHERE user_id = ?",
                (destination.x, destination.y, destination.z, self.clock(), actor),
            )
        return MoveResult(MOVED, destination, current, distance)

    def state_by_name(self, name: str) -> LocationState | None:
        location_id = self.resolve_name(name)
        return self.state(location_id) if location_id is not None else None

    def state(self, location_id: str) -> LocationState:
        definition = self.content.location_definitions[str(location_id)]
        x, y, z = self._coordinates_by_id[str(location_id)]
        return LocationState(
            str(location_id),
            str(location_id),
            str(definition["地点类型"]),
            str(definition["地形"]),
            str(definition["说明"]),
            tuple(str(value) for value in definition["可用功能"]),
            self.content.npcs_in_groups(definition["道侣池"]),
            self.content.enemies_in_groups(definition["敌人池"]),
            x,
            y,
            z,
        )

    def state_at(self, x: int, y: int, z: int) -> LocationState:
        coordinates = int(x), int(y), int(z)
        location_id = self._ids_by_coordinates.get(coordinates)
        if location_id is None:
            raise RuntimeError(f"坐标没有登记地点：{coordinates}")
        return self.state(location_id)

    def all_locations(self) -> tuple[LocationSummary, ...]:
        return tuple(self._summary(location_id) for location_id in self.content.location_definitions)

    def resolve_name(self, value: str) -> str | None:
        name = " ".join(str(value or "").split())
        return name if name in self.content.location_definitions else None

    @staticmethod
    def distance(
        origin: LocationState | LocationSummary,
        destination: LocationState | LocationSummary,
    ) -> int:
        return (
            abs(origin.x - destination.x)
            + abs(origin.y - destination.y)
            + abs(origin.z - destination.z)
        )

    def supports_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        function: str,
    ) -> bool:
        current = self.current_in_connection(connection, user_id)
        return str(function) in current.functions

    def npc_pool_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
    ) -> tuple[str, ...]:
        location_id = self.current_in_connection(connection, user_id).location_id
        return self.content.npcs_in_groups(
            self.content.location_definitions[location_id]["道侣池"]
        )

    def enemy_pool_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
    ) -> tuple[str, ...]:
        location_id = self.current_in_connection(connection, user_id).location_id
        return self.content.enemies_in_groups(
            self.content.location_definitions[location_id]["敌人池"]
        )

    def _summary(self, location_id: str) -> LocationSummary:
        definition = self.content.location_definitions[str(location_id)]
        x, y, z = self._coordinates_by_id[str(location_id)]
        return LocationSummary(
            str(location_id),
            str(location_id),
            str(definition["地点类型"]),
            str(definition["地形"]),
            tuple(str(value) for value in definition["可用功能"]),
            self.content.npcs_in_groups(definition["道侣池"]),
            self.content.enemies_in_groups(definition["敌人池"]),
            x,
            y,
            z,
        )


def _coordinates(definition: dict) -> tuple[int, int, int]:
    value = definition["坐标"]
    return int(value[0]), int(value[1]), int(value[2])


__all__ = [
    "ALREADY_THERE",
    "ACTIVITY_ACTIVE",
    "MOVED",
    "NOT_FOUND",
    "LocationFeature",
    "SCHEMA",
]
