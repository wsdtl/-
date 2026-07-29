"""探险的连续战斗预计算、时间解锁和原子结算。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
import json
import random
import secrets
from typing import Any

from game.content import GameContent
from game.core import Database, elapsed_seconds, record_exists, require_user_id, utc_now
from game.features.didian import LocationFeature
from game.features.diren import EnemyFeature
from game.features.player import PlayerFeature
from game.features.xiushi import NpcFeature, PartnerAsset
from game.rules import BattleEngine, CombatantSnapshot


SCHEMA = """
CREATE TABLE IF NOT EXISTS exploration_states (
    user_id TEXT PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    seed INTEGER NOT NULL,
    asset_revision INTEGER NOT NULL,
    rounds_json TEXT NOT NULL
);
"""
TABLE = "exploration_states"
PEER_TABLE = "seclusion_states"

STARTED = "started"
ALREADY_ACTIVE = "already_active"
SECLUSION_ACTIVE = "seclusion_active"
INSUFFICIENT_STAMINA = "insufficient_stamina"
NO_HEALTH = "no_health"
PARTNER_NO_HEALTH = "partner_no_health"
PARTNER_INSUFFICIENT_STAMINA = "partner_insufficient_stamina"
LOCATION_UNAVAILABLE = "location_unavailable"


@dataclass(frozen=True)
class ExplorationStart:
    status: str
    planned_rounds: int = 0
    location_name: str = ""
    partners: tuple[str, ...] = ()
    blocked_partner: str = ""


@dataclass(frozen=True)
class ExplorationProgress:
    started_at: str
    elapsed_seconds: int
    completed_rounds: int
    planned_rounds: int
    ready: bool
    partners: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExplorationSettlement:
    elapsed_seconds: int
    completed_rounds: int
    victories: int
    defeats: int
    spirit_stones: int
    weapon_experience: int
    weapon_levels_gained: int
    consumed_items: dict[str, int]
    drops: dict[str, int]
    encounters: tuple[dict[str, Any], ...]
    partners: tuple[str, ...] = ()


class ExplorationFeature:
    def __init__(
        self,
        database: Database,
        content: GameContent,
        player: PlayerFeature,
        location: LocationFeature,
        enemy: EnemyFeature,
        npc: NpcFeature,
        battle: BattleEngine,
        *,
        clock: Callable[[], str] = utc_now,
        seed_factory: Callable[[], int] | None = None,
    ) -> None:
        self.database = database
        self.content = content
        self.player = player
        self.location = location
        self.enemy = enemy
        self.npc = npc
        self.battle = battle
        self.clock = clock
        self.seed_factory = seed_factory or (lambda: secrets.randbits(63))

    @property
    def rules(self) -> dict[str, Any]:
        return self.content.activities["探险"]

    def initialize(self) -> None:
        self.database.initialize(SCHEMA)

    def active(self, user_id: str) -> bool:
        actor = require_user_id(user_id)
        with self.database.transaction() as connection:
            return record_exists(connection, TABLE, actor)

    def start(self, user_id: str, display_name: str = "") -> ExplorationStart:
        actor = require_user_id(user_id)
        with self.database.transaction(write=True) as connection:
            self.player.ensure_in_connection(connection, actor, display_name)
            if record_exists(connection, PEER_TABLE, actor):
                return ExplorationStart(SECLUSION_ACTIVE)
            if record_exists(connection, TABLE, actor):
                row = connection.execute(
                    "SELECT rounds_json FROM exploration_states WHERE user_id = ?",
                    (actor,),
                ).fetchone()
                existing = _load_rounds(row["rounds_json"])
                return ExplorationStart(
                    ALREADY_ACTIVE,
                    len(existing),
                    partners=_party_names(existing),
                )

            current_location = self.location.current_in_connection(connection, actor)
            enemy_pool = self.location.enemy_pool_in_connection(connection, actor)
            if "探险" not in current_location.functions or not enemy_pool:
                return ExplorationStart(
                    LOCATION_UNAVAILABLE,
                    location_name=current_location.label,
                )

            assets = self.player.load_assets_in_connection(connection, actor)
            partners = self.npc.party_assets_in_connection(connection, actor)
            cost = int(self.rules["每轮体力消耗"])
            if assets.player.health <= 0:
                return ExplorationStart(NO_HEALTH)
            if assets.player.stamina < cost:
                return ExplorationStart(INSUFFICIENT_STAMINA)
            for partner in partners:
                if partner.health <= 0:
                    return ExplorationStart(
                        PARTNER_NO_HEALTH,
                        partners=tuple(value.npc_id for value in partners),
                        blocked_partner=partner.npc_id,
                    )
                if partner.stamina < cost:
                    return ExplorationStart(
                        PARTNER_INSUFFICIENT_STAMINA,
                        partners=tuple(value.npc_id for value in partners),
                        blocked_partner=partner.npc_id,
                    )

            seed = int(self.seed_factory())
            rounds = self._plan_rounds(assets, partners, seed, enemy_pool)
            connection.execute(
                """
                INSERT INTO exploration_states(
                    user_id, started_at, seed, asset_revision, rounds_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    actor,
                    self.clock(),
                    seed,
                    assets.player.revision,
                    _json(rounds),
                ),
            )
        return ExplorationStart(
            STARTED,
            len(rounds),
            current_location.label,
            tuple(value.npc_id for value in partners),
        )

    def progress(self, user_id: str) -> ExplorationProgress | None:
        actor = require_user_id(user_id)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT started_at, rounds_json FROM exploration_states WHERE user_id = ?",
                (actor,),
            ).fetchone()
        if row is None:
            return None
        rounds = _load_rounds(row["rounds_json"])
        return self._progress(
            str(row["started_at"]),
            len(rounds),
            self.clock(),
            _party_names(rounds),
        )

    def end(self, user_id: str) -> ExplorationSettlement | None:
        actor = require_user_id(user_id)
        with self.database.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM exploration_states WHERE user_id = ?",
                (actor,),
            ).fetchone()
            if row is None:
                return None
            rounds = _load_rounds(row["rounds_json"])
            progress = self._progress(
                str(row["started_at"]),
                len(rounds),
                self.clock(),
                _party_names(rounds),
            )
            completed = rounds[: progress.completed_rounds]
            if completed:
                self._apply_round_state(connection, actor, int(row["asset_revision"]), completed)
                rewards = self._apply_rewards(connection, actor, completed)
            else:
                rewards = (0, 0, 0, Counter(), Counter())
            connection.execute("DELETE FROM exploration_states WHERE user_id = ?", (actor,))

        stones, weapon_exp, weapon_levels, consumed, drops = rewards
        victories = sum(value["result"] == "victory" for value in completed)
        defeats = sum(value["result"] != "victory" for value in completed)
        encounters = tuple(
            {
                "round": value["round"],
                "enemy": value["enemy_name"],
                "enemy_level": value["enemy_level"],
                "result": value["result"],
            }
            for value in completed
        )
        return ExplorationSettlement(
            progress.elapsed_seconds,
            len(completed),
            victories,
            defeats,
            stones,
            weapon_exp,
            weapon_levels,
            dict(consumed),
            dict(drops),
            encounters,
            progress.partners,
        )

    def _plan_rounds(
        self,
        assets,
        partners: tuple[PartnerAsset, ...],
        seed: int,
        enemy_pool: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        rules = self.rules
        rng = random.Random(seed)
        health = assets.player.health
        spirit = assets.player.spirit
        shield = 0.0
        stamina = assets.player.stamina
        statuses = list(assets.player.statuses)
        cooldowns: dict[str, int] = {}
        skill_cursor = 0
        inventory = dict(assets.inventory)
        techniques = self.player.battle_techniques(assets.techniques)
        party_states = {
            partner.npc_id: {
                "npc_id": partner.npc_id,
                "combatant_id": partner.combatant_id,
                "revision": partner.revision,
                "health": partner.health,
                "spirit": partner.spirit,
                "stamina": partner.stamina,
                "shield": 0.0,
                "statuses": [dict(value) for value in partner.statuses],
                "cooldowns": {},
                "skill_cursor": 0,
            }
            for partner in partners
        }
        item_definitions = self.content.combat_item_definitions()
        result: list[dict[str, Any]] = []
        cost = int(rules["每轮体力消耗"])

        for number in range(1, int(rules["最多轮数"]) + 1):
            if (
                stamina < cost
                or health <= 0
                or any(
                    float(value["health"]) <= 0 or float(value["stamina"]) < cost
                    for value in party_states.values()
                )
            ):
                break
            stamina -= cost
            active_partners: list[PartnerAsset] = []
            for partner in partners:
                state = party_states[partner.npc_id]
                if float(state["health"]) <= 0 or float(state["stamina"]) < cost:
                    continue
                state["stamina"] = float(state["stamina"]) - cost
                partner.health = float(state["health"])
                partner.spirit = float(state["spirit"])
                partner.stamina = float(state["stamina"])
                partner.statuses = [dict(value) for value in state["statuses"]]
                active_partners.append(partner)
            enemy_id = self.content.choose_enemy(enemy_pool, rng)
            enemy_seed = rng.getrandbits(63)
            enemy = self.enemy.spawn(enemy_id, seed=enemy_seed)
            battle_seed = rng.getrandbits(63)
            player_snapshot = CombatantSnapshot(
                id=f"player:{assets.player.user_id}",
                name=assets.player.name,
                attributes=assets.player.attributes,
                level=assets.player.level,
                kind="修士",
                health=health,
                spirit=spirit,
                shield=shield,
                statuses=tuple(statuses),
                weapon_attack=self.player.weapon_attack(assets.weapon),
                techniques=tuple(techniques),
                inventory=inventory,
                auto_medicine=assets.player.auto_medicine,
                medicine_threshold=float(rules["自动用药阈值"]),
                cooldowns=cooldowns,
                skill_cursor=skill_cursor,
            )
            enemy_snapshot = enemy.battle_snapshot()
            partner_snapshots = tuple(
                self.npc.battle_snapshot(
                    partner,
                    inventory=inventory,
                    auto_medicine=assets.player.auto_medicine,
                    medicine_threshold=float(rules["自动用药阈值"]),
                    shield=float(party_states[partner.npc_id]["shield"]),
                    cooldowns=dict(party_states[partner.npc_id]["cooldowns"]),
                    skill_cursor=int(party_states[partner.npc_id]["skill_cursor"]),
                )
                for partner in active_partners
            )
            outcome = self.battle.simulate_teams(
                left=(player_snapshot, *partner_snapshots),
                right=(enemy_snapshot,),
                item_definitions=item_definitions,
                seed=battle_seed,
                action_limit=int(rules["战斗行动上限"]),
                share_left_inventory=True,
            )
            player_result = next(
                value for value in outcome.left_results if value.id == player_snapshot.id
            )
            inventory = dict(player_result.inventory)
            health = player_result.health
            spirit = player_result.spirit
            shield = player_result.shield
            statuses = [value.to_dict() for value in player_result.statuses]
            cooldowns = dict(player_result.cooldowns)
            skill_cursor = player_result.skill_cursor
            partner_results = {value.id: value for value in outcome.left_results[1:]}
            for partner in active_partners:
                partner_result = partner_results[partner.combatant_id]
                state = party_states[partner.npc_id]
                state.update(
                    {
                        "health": partner_result.health,
                        "spirit": partner_result.spirit,
                        "shield": partner_result.shield,
                        "statuses": [value.to_dict() for value in partner_result.statuses],
                        "cooldowns": dict(partner_result.cooldowns),
                        "skill_cursor": partner_result.skill_cursor,
                    }
                )
            battle_result = (
                "victory"
                if outcome.winner_side == "left"
                else "draw"
                if outcome.draw
                else "defeat"
            )
            consumed_items: Counter[str] = Counter()
            for combatant in outcome.left_results:
                consumed_items.update(
                    {str(key): int(value) for key, value in combatant.consumed_items.items()}
                )
            result.append(
                {
                    "round": number,
                    "enemy_id": enemy_id,
                    "enemy_name": enemy_id,
                    "enemy_level": enemy.level,
                    "enemy_kind": enemy.kind,
                    "result": battle_result,
                    "actions": outcome.actions,
                    "health": health,
                    "spirit": spirit,
                    "shield": shield,
                    "stamina": stamina,
                    "statuses": statuses,
                    "cooldowns": cooldowns,
                    "skill_cursor": skill_cursor,
                    "party": [dict(party_states[value.npc_id]) for value in partners],
                    "consumed_items": dict(consumed_items),
                    "enemy_spirit_stones": enemy.spirit_stones,
                    "enemy_drops": enemy.defeated_items(outcome.right.inventory),
                    "weapon_experience": _roll_range(
                        random.Random(enemy_seed ^ battle_seed),
                        self.content.enemy_definitions[enemy_id]["交锋所得"]["本命武器经验"],
                    ),
                }
            )
            if battle_result != "victory":
                break
        return result

    def _progress(
        self,
        started_at: str,
        planned_rounds: int,
        now: str,
        partners: tuple[str, ...] = (),
    ) -> ExplorationProgress:
        duration = int(self.rules["持续秒数"])
        elapsed = min(duration, elapsed_seconds(started_at, now))
        unlocked = min(planned_rounds, elapsed // int(self.rules["每轮秒数"]))
        return ExplorationProgress(
            started_at,
            elapsed,
            unlocked,
            planned_rounds,
            elapsed >= duration,
            partners,
        )

    def _apply_round_state(
        self,
        connection,
        user_id: str,
        expected_revision: int,
        rounds: list[dict[str, Any]],
    ) -> None:
        player = self.player.load_player_in_connection(connection, user_id)
        if player.revision != expected_revision:
            raise RuntimeError("探险期间人物资产发生变化，已拒绝覆盖")
        final = rounds[-1]
        player.health = float(final["health"])
        player.spirit = float(final["spirit"])
        player.stamina = float(final["stamina"])
        player.statuses = [dict(value) for value in final["statuses"]]
        self.player.update_player_in_connection(
            connection,
            player,
            expected_revision=expected_revision,
        )
        if "party" in final:
            self.npc.apply_exploration_states_in_connection(
                connection,
                user_id,
                [dict(value) for value in final.get("party") or ()],
            )

    def _apply_rewards(self, connection, user_id: str, rounds: list[dict[str, Any]]):
        weapon = self.player.load_weapon_in_connection(connection, user_id)
        stones = 0
        weapon_exp = 0
        consumed: Counter[str] = Counter()
        drops: Counter[str] = Counter()
        for value in rounds:
            for item_id, quantity in value["consumed_items"].items():
                consumed[str(item_id)] += int(quantity)
            if value["result"] != "victory":
                continue
            stones += int(value["enemy_spirit_stones"])
            weapon_exp += int(value["weapon_experience"])
            for item_id, quantity in value["enemy_drops"].items():
                drops[str(item_id)] += int(quantity)

        for item_id, quantity in consumed.items():
            resolved = self.player.resolve_item(item_id)
            if resolved is None:
                raise RuntimeError(f"探险结算包含未知消耗物品：{item_id}")
            base_item_id, grade_id = resolved
            if not self.player.remove_item_in_connection(
                connection,
                user_id,
                base_item_id,
                quantity,
                grade_id,
            ):
                raise RuntimeError(f"探险结算缺少已消耗物品：{item_id}")
        player = self.player.load_player_in_connection(connection, user_id)
        player.spirit_stones += stones
        self.player.update_player_in_connection(
            connection,
            player,
            expected_revision=player.revision,
        )
        weapon_levels = self.player.gain_weapon_experience(weapon, weapon_exp)
        self.player.update_weapon_in_connection(connection, weapon)
        self.npc.gain_party_weapon_experience_in_connection(
            connection,
            user_id,
            weapon_exp,
            tuple(
                str(value["npc_id"])
                for value in (rounds[0].get("party") or ())
            ),
        )
        for item_id, quantity in drops.items():
            resolved = self.player.resolve_item(item_id)
            if resolved is None:
                raise RuntimeError(f"探险结算包含未知掉落物品：{item_id}")
            base_item_id, grade_id = resolved
            self.player.add_item_in_connection(
                connection,
                user_id,
                base_item_id,
                quantity,
                grade_id,
            )
        return stones, weapon_exp, weapon_levels, consumed, drops


def _roll_range(rng: random.Random, value: list[int]) -> int:
    return rng.randint(int(value[0]), int(value[1]))


def _load_rounds(value: str) -> list[dict[str, Any]]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, list):
        raise ValueError("探险轮次数据损坏")
    return [dict(item) for item in loaded]


def _party_names(rounds: list[dict[str, Any]]) -> tuple[str, ...]:
    if not rounds:
        return ()
    return tuple(str(value["npc_id"]) for value in rounds[0].get("party") or ())


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "ALREADY_ACTIVE",
    "INSUFFICIENT_STAMINA",
    "LOCATION_UNAVAILABLE",
    "NO_HEALTH",
    "PARTNER_INSUFFICIENT_STAMINA",
    "PARTNER_NO_HEALTH",
    "SECLUSION_ACTIVE",
    "STARTED",
    "ExplorationFeature",
    "ExplorationProgress",
    "ExplorationSettlement",
    "ExplorationStart",
]
