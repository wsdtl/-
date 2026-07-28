"""闭关的开始事实、时间进度和原子结算。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import random
import secrets

from game.content import GameContent
from game.core import Database, elapsed_seconds, record_exists, require_user_id, utc_now
from game.features.didian import LocationFeature
from game.features.player import PlayerFeature, TechniqueState


SCHEMA = """
CREATE TABLE IF NOT EXISTS seclusion_states (
    user_id TEXT PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    seed INTEGER NOT NULL
);
"""
TABLE = "seclusion_states"
PEER_TABLE = "exploration_states"

STARTED = "started"
ALREADY_ACTIVE = "already_active"
EXPLORATION_ACTIVE = "exploration_active"
LOCATION_UNAVAILABLE = "location_unavailable"


@dataclass(frozen=True)
class SeclusionProgress:
    started_at: str
    elapsed_seconds: int
    completed_rounds: int
    maximum_rounds: int
    ready: bool


@dataclass(frozen=True)
class SeclusionSettlement:
    elapsed_seconds: int
    completed_rounds: int
    experience: int
    levels_gained: int
    breakthrough_pending: bool
    recovered_health: float
    recovered_spirit: float
    recovered_stamina: float
    techniques: tuple[TechniqueState, ...]


class SeclusionFeature:
    def __init__(
        self,
        database: Database,
        content: GameContent,
        player: PlayerFeature,
        location: LocationFeature,
        *,
        clock: Callable[[], str] = utc_now,
        seed_factory: Callable[[], int] | None = None,
    ) -> None:
        self.database = database
        self.content = content
        self.player = player
        self.location = location
        self.clock = clock
        self.seed_factory = seed_factory or (lambda: secrets.randbits(63))

    @property
    def rules(self) -> dict:
        return self.content.activities["闭关"]

    @property
    def maximum_rounds(self) -> int:
        return int(self.rules["持续秒数"]) // int(self.rules["每轮秒数"])

    def initialize(self) -> None:
        self.database.initialize(SCHEMA)

    def active(self, user_id: str) -> bool:
        actor = require_user_id(user_id)
        with self.database.transaction() as connection:
            return record_exists(connection, TABLE, actor)

    def start(self, user_id: str, display_name: str = "") -> str:
        actor = require_user_id(user_id)
        with self.database.transaction(write=True) as connection:
            self.player.ensure_in_connection(connection, actor, display_name)
            if record_exists(connection, PEER_TABLE, actor):
                return EXPLORATION_ACTIVE
            if not self.location.supports_in_connection(connection, actor, "闭关"):
                return LOCATION_UNAVAILABLE
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO seclusion_states(user_id, started_at, seed)
                VALUES (?, ?, ?)
                """,
                (actor, self.clock(), int(self.seed_factory())),
            )
        return STARTED if cursor.rowcount == 1 else ALREADY_ACTIVE

    def progress(self, user_id: str) -> SeclusionProgress | None:
        actor = require_user_id(user_id)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT started_at FROM seclusion_states WHERE user_id = ?",
                (actor,),
            ).fetchone()
        if row is None:
            return None
        return self._progress(str(row["started_at"]), self.clock())

    def end(self, user_id: str) -> SeclusionSettlement | None:
        actor = require_user_id(user_id)
        with self.database.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT started_at, seed FROM seclusion_states WHERE user_id = ?",
                (actor,),
            ).fetchone()
            if row is None:
                return None

            progress = self._progress(str(row["started_at"]), self.clock())
            player = self.player.load_player_in_connection(connection, actor)
            before_revision = player.revision
            experience = int(self.rules["每轮经验"]) * progress.completed_rounds
            experience_result = self.player.gain_experience(player, experience)
            ratio = min(1.0, progress.elapsed_seconds / int(self.rules["持续秒数"]))
            recovered = {}
            for resource, resource_name in (
                ("health", "血气"),
                ("spirit", "精神"),
                ("stamina", "体力"),
            ):
                old = float(getattr(player, resource))
                maximum = player.resource_maximum(resource_name)
                value = min(maximum, old + (maximum - old) * ratio)
                setattr(player, resource, value)
                recovered[resource] = value - old

            if progress.ready and self.rules.get("圆满时清除临时状态"):
                player.statuses.clear()

            techniques = self._settle_techniques(
                connection,
                actor,
                int(row["seed"]),
                progress.completed_rounds,
            )
            self.player.update_player_in_connection(
                connection,
                player,
                expected_revision=before_revision,
            )
            connection.execute("DELETE FROM seclusion_states WHERE user_id = ?", (actor,))

        return SeclusionSettlement(
            progress.elapsed_seconds,
            progress.completed_rounds,
            experience_result.applied,
            experience_result.levels_gained,
            experience_result.locked,
            recovered["health"],
            recovered["spirit"],
            recovered["stamina"],
            tuple(techniques),
        )

    def _progress(self, started_at: str, now: str) -> SeclusionProgress:
        duration = int(self.rules["持续秒数"])
        elapsed = min(duration, elapsed_seconds(started_at, now))
        completed = min(self.maximum_rounds, elapsed // int(self.rules["每轮秒数"]))
        return SeclusionProgress(
            started_at,
            elapsed,
            completed,
            self.maximum_rounds,
            elapsed >= duration,
        )

    def _settle_techniques(
        self,
        connection,
        user_id: str,
        seed: int,
        rounds: int,
    ) -> list[TechniqueState]:
        result: list[TechniqueState] = []
        root = random.Random(seed)
        chance = float(self.rules["感悟功法概率"])
        for _ in range(rounds):
            rng = random.Random(root.getrandbits(63))
            if rng.random() <= chance:
                result.append(
                    self.player.create_random_technique_in_connection(
                        connection,
                        user_id,
                        rng,
                    )
                )
        return result


__all__ = [
    "ALREADY_ACTIVE",
    "EXPLORATION_ACTIVE",
    "LOCATION_UNAVAILABLE",
    "STARTED",
    "SeclusionFeature",
    "SeclusionProgress",
    "SeclusionSettlement",
]
