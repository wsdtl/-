"""地点修士的交谈、结为道侣与同行关系。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
import random
import secrets
from typing import Any

from game.content import GameContent
from game.core import Database, require_user_id, utc_now
from game.features.didian import LocationFeature
from game.features.loadout import configure_battle_instances, roll_loadout
from game.features.player import ItemUseResult, PlayerFeature
from game.rules import CombatantResult, CombatantSnapshot


SCHEMA = """
CREATE TABLE IF NOT EXISTS partner_relations (
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    npc_id TEXT NOT NULL,
    favor INTEGER NOT NULL DEFAULT 0 CHECK (favor >= 0),
    reward_claimed INTEGER NOT NULL DEFAULT 0 CHECK (reward_claimed IN (0, 1)),
    in_party INTEGER NOT NULL DEFAULT 0 CHECK (in_party IN (0, 1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, npc_id)
);

CREATE INDEX IF NOT EXISTS ix_partner_relations_user_party
ON partner_relations(user_id, in_party);

CREATE TABLE IF NOT EXISTS partner_assets (
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    npc_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    loadout_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, npc_id),
    FOREIGN KEY (user_id, npc_id)
        REFERENCES partner_relations(user_id, npc_id) ON DELETE CASCADE
);
"""

GIFTED = "gifted"
INVALID_ITEM = "invalid_item"
NOT_PREFERRED = "not_preferred"
INSUFFICIENT_ITEM = "insufficient_item"
FAVOR_FULL = "favor_full"
NOT_NEARBY = "not_nearby"
INVITED = "invited"
ALREADY_IN_PARTY = "already_in_party"
FAVOR_REQUIRED = "favor_required"
LEFT_PARTY = "left_party"
NOT_IN_PARTY = "not_in_party"


@dataclass(frozen=True)
class NpcProfile:
    npc_id: str
    title: str
    stance: str
    description: str
    interactive: bool
    directions: tuple[str, ...]
    level: int
    home_location: str
    favor: int
    favor_max: int
    in_party: bool
    favorite_item_groups: tuple[str, ...]
    favorite_items: tuple[str, ...]

    @property
    def level_text(self) -> str:
        return f"Lv{self.level}"

    @property
    def favor_text(self) -> str:
        return f"{self.favor}/{self.favor_max}"

    @property
    def relation_text(self) -> str:
        return "同行中" if self.in_party else f"常驻{self.home_location}"

    @property
    def preference_text(self) -> str:
        return "钟爱" + "、".join(self.favorite_items)


@dataclass(frozen=True)
class GiftResult:
    status: str
    profile: NpcProfile | None = None
    given_items: Mapping[str, int] = field(default_factory=dict)
    favor_gained: int = 0
    reward_name: str = ""
    reward_quantity: int = 0


@dataclass(frozen=True)
class PartyResult:
    status: str
    profile: NpcProfile | None = None
    line: str = ""
    partner: "PartnerAsset | None" = None


@dataclass
class PartnerAsset:
    user_id: str
    npc_id: str
    direction_id: str
    aptitude: int
    level: int
    experience: int
    attributes: dict[str, float]
    health: float
    spirit: float
    stamina: float
    statuses: list[dict[str, Any]]
    weapon: dict[str, Any]
    techniques: list[dict[str, Any]]
    enchantments: list[dict[str, Any]]
    gems: list[dict[str, Any]]
    revision: int = 0

    @property
    def combatant_id(self) -> str:
        return f"partner:{self.user_id}:{self.npc_id}"

    def resource_maximum(self, resource: str) -> float:
        return max(0.0, float(self.attributes.get(f"{resource}上限", 0.0)))


@dataclass(frozen=True)
class PartnerSeclusionResult:
    npc_id: str
    experience: int
    levels_gained: int
    level: int
    recovered_health: float
    recovered_spirit: float
    recovered_stamina: float


class NpcFeature:
    def __init__(
        self,
        database: Database,
        content: GameContent,
        location: LocationFeature,
        player: PlayerFeature,
        *,
        clock: Callable[[], str] = utc_now,
        seed_factory: Callable[[], int] | None = None,
    ) -> None:
        self.database = database
        self.content = content
        self.location = location
        self.player = player
        self.clock = clock
        self.seed_factory = seed_factory or (lambda: secrets.randbits(63))
        self.home_locations = self.content.npc_home_locations
        self.favor_max = int(self.content.player["道侣"]["好感上限"])

    def initialize(self) -> None:
        self.database.initialize(SCHEMA)
        with self.database.transaction(write=True) as connection:
            missing = connection.execute(
                """
                SELECT relations.user_id, relations.npc_id
                FROM partner_relations AS relations
                LEFT JOIN partner_assets AS assets
                  ON assets.user_id = relations.user_id
                 AND assets.npc_id = relations.npc_id
                WHERE relations.in_party = 1 AND assets.npc_id IS NULL
                """
            ).fetchall()
            for row in missing:
                self._ensure_partner_asset(
                    connection,
                    str(row["user_id"]),
                    str(row["npc_id"]),
                )

    def nearby(self, user_id: str, display_name: str = "") -> tuple[NpcProfile, ...]:
        actor = require_user_id(user_id)
        current = self.location.current(actor, display_name)
        return self.at_location(actor, current.location_id, display_name)

    def at_location(
        self,
        user_id: str,
        location_id: str,
        display_name: str = "",
    ) -> tuple[NpcProfile, ...]:
        actor = require_user_id(user_id)
        self.player.ensure(actor, display_name)
        current = self.location.current(actor, display_name)
        target_id = str(location_id)
        resident_ids = self.content.npcs_in_groups(
            list(self.content.location_definitions[target_id]["道侣池"])
        )
        with self.database.transaction() as connection:
            relations = self._relations(connection, actor)
        visible = [
            npc_id
            for npc_id in resident_ids
            if not bool((relations.get(npc_id) or {}).get("in_party"))
        ]
        if target_id == current.location_id:
            visible.extend(
                npc_id
                for npc_id in self.content.npc_definitions
                if bool((relations.get(npc_id) or {}).get("in_party"))
            )
        return tuple(
            self._profile(npc_id, relations.get(npc_id))
            for npc_id in dict.fromkeys(visible)
        )

    def party(self, user_id: str, display_name: str = "") -> tuple[NpcProfile, ...]:
        actor = require_user_id(user_id)
        self.player.ensure(actor, display_name)
        with self.database.transaction() as connection:
            relations = self._relations(connection, actor)
        return tuple(
            self._profile(npc_id, relations[npc_id])
            for npc_id in self.content.npc_definitions
            if bool((relations.get(npc_id) or {}).get("in_party"))
        )

    def partner(self, user_id: str, npc_name: str) -> PartnerAsset | None:
        actor = require_user_id(user_id)
        npc_id = " ".join(str(npc_name or "").split())
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM partner_assets WHERE user_id = ? AND npc_id = ?",
                (actor, npc_id),
            ).fetchone()
        return _partner_asset(row) if row is not None else None

    def party_assets(self, user_id: str) -> tuple[PartnerAsset, ...]:
        actor = require_user_id(user_id)
        with self.database.transaction() as connection:
            return self.party_assets_in_connection(connection, actor)

    def use_experience_item(
        self,
        user_id: str,
        npc_name: str,
        item_name: str,
        quantity: int = 1,
        display_name: str = "",
    ) -> ItemUseResult:
        actor = require_user_id(user_id)
        npc_id = " ".join(str(npc_name or "").split())
        if not npc_id:
            return ItemUseResult("partner_required", str(item_name or "").strip())
        resolved = self.player.resolve_item(item_name)
        if resolved is None:
            return ItemUseResult("not_found")
        item_id, requested_grade = resolved
        shown_name = self.player.item_name(item_id, requested_grade) if requested_grade else item_id
        use = self.content.item_definitions[item_id].get("使用效果")
        if not isinstance(use, dict) or use.get("类型") != "增加道侣经验":
            return ItemUseResult("not_usable", shown_name)
        requested_count = max(1, int(quantity))
        with self.database.transaction(write=True) as connection:
            self.player.ensure_in_connection(connection, actor, display_name)
            row = connection.execute(
                "SELECT * FROM partner_assets WHERE user_id = ? AND npc_id = ?",
                (actor, npc_id),
            ).fetchone()
            if row is None:
                return ItemUseResult("target_not_found", shown_name, target=npc_id)
            partner = _partner_asset(row)
            if partner.level >= int(self.content.player["人物"]["等级上限"]):
                return ItemUseResult(
                    "progress_locked",
                    shown_name,
                    effect="增加道侣经验",
                    target=partner.npc_id,
                )
            taken = self.player.take_item_in_connection(
                connection,
                actor,
                item_id,
                requested_count,
                requested_grade,
            )
            if taken is None:
                return ItemUseResult("insufficient", shown_name)
            applied, levels = self._gain_partner_experience(
                partner,
                int(use["经验"]) * requested_count,
            )
            self._update_partner_asset(connection, partner)
        return ItemUseResult(
            "used",
            shown_name,
            requested_count,
            effect="增加道侣经验",
            experience=applied,
            levels_gained=levels,
            target=partner.npc_id,
        )

    @staticmethod
    def party_assets_in_connection(connection, user_id: str) -> tuple[PartnerAsset, ...]:
        return tuple(
            _partner_asset(row)
            for row in connection.execute(
                """
                SELECT assets.*
                FROM partner_assets AS assets
                JOIN partner_relations AS relations
                  ON relations.user_id = assets.user_id
                 AND relations.npc_id = assets.npc_id
                WHERE assets.user_id = ? AND relations.in_party = 1
                ORDER BY assets.npc_id
                """,
                (user_id,),
            )
        )

    def nearby_profile(
        self,
        user_id: str,
        npc_name: str,
        display_name: str = "",
    ) -> NpcProfile | None:
        name = " ".join(str(npc_name or "").split())
        return next(
            (npc for npc in self.nearby(user_id, display_name) if npc.npc_id == name),
            None,
        )

    def talk(
        self,
        user_id: str,
        npc_name: str,
        *,
        display_name: str = "",
        seed: int | None = None,
    ) -> tuple[NpcProfile, str] | None:
        profile = self.nearby_profile(user_id, npc_name, display_name)
        if profile is None or not profile.interactive:
            return None
        dialogue = tuple(
            str(value)
            for value in self.content.npc_definitions[profile.npc_id]["身份"]["话语"]
        )
        rng = random.Random(seed) if seed is not None else random.SystemRandom()
        return profile, rng.choice(dialogue)

    def gift(
        self,
        user_id: str,
        npc_name: str,
        item_name: str,
        quantity: int = 1,
        display_name: str = "",
    ) -> GiftResult:
        actor = require_user_id(user_id)
        npc_id = " ".join(str(npc_name or "").split())
        resolved = self.player.resolve_item(item_name)
        if resolved is None:
            return GiftResult(INVALID_ITEM)
        item_id, requested_grade = resolved
        definition = self.content.npc_definitions.get(npc_id)
        if definition is None:
            return GiftResult(NOT_NEARBY)
        relationship = definition["结交"]
        favorite_items = self.content.items_in_groups(
            list(relationship["喜爱天材地宝池"])
        )
        if item_id not in favorite_items:
            return GiftResult(NOT_PREFERRED)

        amount = max(1, int(quantity))
        with self.database.transaction(write=True) as connection:
            self.player.ensure_in_connection(connection, actor, display_name)
            current = self.location.current_in_connection(connection, actor)
            relation = self._relation(connection, actor, npc_id)
            if not self._is_nearby(npc_id, current.location_id, relation):
                return GiftResult(NOT_NEARBY)
            profile = self._profile(npc_id, relation)
            if profile.favor >= self.favor_max:
                return GiftResult(FAVOR_FULL, profile)
            taken = self.player.take_item_in_connection(
                connection,
                actor,
                item_id,
                amount,
                requested_grade,
            )
            if taken is None:
                return GiftResult(INSUFFICIENT_ITEM, profile)

            raw_gain = 0
            for full_name, count in taken.items():
                taken_item_id, grade_id = self.player.resolve_item(full_name) or ("", "")
                graded = self.content.graded_item_definition(taken_item_id, str(grade_id))
                score = int(graded["评分"])
                raw_gain += max(1, score) * int(count)
            favor = min(self.favor_max, profile.favor + raw_gain)
            gained = favor - profile.favor
            reward_claimed = bool((relation or {}).get("reward_claimed"))
            reward_name = ""
            reward_quantity = 0
            if favor >= self.favor_max and not reward_claimed:
                reward = relationship["圆满回礼"]
                reward_item = str(reward["物品"])
                reward_grade = str(reward["品级"])
                reward_quantity = int(reward["数量"])
                self.player.add_item_in_connection(
                    connection,
                    actor,
                    reward_item,
                    reward_quantity,
                    reward_grade,
                )
                reward_name = self.player.item_name(reward_item, reward_grade)
                reward_claimed = True
            self._save_relation(
                connection,
                actor,
                npc_id,
                favor,
                reward_claimed,
                bool((relation or {}).get("in_party")),
            )
            updated = self._profile(
                npc_id,
                {
                    "favor": favor,
                    "reward_claimed": reward_claimed,
                    "in_party": bool((relation or {}).get("in_party")),
                    "state_json": (relation or {}).get("state_json"),
                },
            )
        return GiftResult(
            GIFTED,
            updated,
            taken,
            gained,
            reward_name,
            reward_quantity,
        )

    def invite(
        self,
        user_id: str,
        npc_name: str,
        display_name: str = "",
    ) -> PartyResult:
        actor = require_user_id(user_id)
        npc_id = " ".join(str(npc_name or "").split())
        if npc_id not in self.content.npc_definitions:
            return PartyResult(NOT_NEARBY)
        with self.database.transaction(write=True) as connection:
            self.player.ensure_in_connection(connection, actor, display_name)
            current = self.location.current_in_connection(connection, actor)
            relation = self._relation(connection, actor, npc_id)
            if not self._is_nearby(npc_id, current.location_id, relation):
                return PartyResult(NOT_NEARBY)
            profile = self._profile(npc_id, relation)
            if profile.in_party:
                return PartyResult(ALREADY_IN_PARTY, profile)
            if profile.favor < self.favor_max:
                return PartyResult(FAVOR_REQUIRED, profile)
            reward_claimed = bool((relation or {}).get("reward_claimed"))
            self._save_relation(
                connection,
                actor,
                npc_id,
                profile.favor,
                reward_claimed,
                True,
            )
            partner = self._ensure_partner_asset(connection, actor, npc_id)
            updated = self._profile(
                npc_id,
                {
                    "favor": profile.favor,
                    "reward_claimed": reward_claimed,
                    "in_party": True,
                    "state_json": _json(_partner_state(partner)),
                },
            )
        return PartyResult(
            INVITED,
            updated,
            str(self.content.npc_definitions[npc_id]["结交"]["入队话语"]),
            partner,
        )

    def leave(
        self,
        user_id: str,
        npc_name: str,
        display_name: str = "",
    ) -> PartyResult:
        actor = require_user_id(user_id)
        npc_id = " ".join(str(npc_name or "").split())
        if npc_id not in self.content.npc_definitions:
            return PartyResult(NOT_IN_PARTY)
        with self.database.transaction(write=True) as connection:
            self.player.ensure_in_connection(connection, actor, display_name)
            relation = self._relation(connection, actor, npc_id)
            profile = self._profile(npc_id, relation)
            if not profile.in_party:
                return PartyResult(NOT_IN_PARTY, profile)
            self._save_relation(
                connection,
                actor,
                npc_id,
                profile.favor,
                bool((relation or {}).get("reward_claimed")),
                False,
            )
            updated = self._profile(
                npc_id,
                {
                    "favor": profile.favor,
                    "reward_claimed": bool((relation or {}).get("reward_claimed")),
                    "in_party": False,
                    "state_json": (relation or {}).get("state_json"),
                },
            )
        return PartyResult(
            LEFT_PARTY,
            updated,
            str(self.content.npc_definitions[npc_id]["结交"]["离队话语"]),
        )

    def _profile(self, npc_id: str, relation: Mapping | None) -> NpcProfile:
        definition = self.content.npc_definitions[npc_id]
        identity = definition["身份"]
        relationship = definition["结交"]
        state = relation or {}
        asset_state = (
            json.loads(str(state["state_json"]))
            if state.get("state_json")
            else {}
        )
        return NpcProfile(
            npc_id=npc_id,
            title=str(identity["称号"]),
            stance=str(identity["立场"]),
            description=str(definition["说明"]),
            interactive=bool(identity["可交互"]),
            directions=(str(asset_state["方向"]),)
            if asset_state
            else (str(definition["修行方向"]),),
            level=int(asset_state.get("等级") or definition["等级"]),
            home_location=self.home_locations[npc_id],
            favor=int(state.get("favor") or 0),
            favor_max=self.favor_max,
            in_party=bool(state.get("in_party")),
            favorite_item_groups=tuple(
                str(value) for value in relationship["喜爱天材地宝池"]
            ),
            favorite_items=self.content.items_in_groups(
                list(relationship["喜爱天材地宝池"])
            ),
        )

    def battle_snapshot(
        self,
        partner: PartnerAsset,
        *,
        inventory: Mapping[str, int],
        auto_medicine: bool,
        medicine_threshold: float,
        shield: float = 0.0,
        cooldowns: Mapping[str, int] | None = None,
        skill_cursor: int = 0,
    ) -> CombatantSnapshot:
        loadout = configure_battle_instances(
            self.content,
            techniques=partner.techniques,
            enchantments=partner.enchantments,
            gems=partner.gems,
            instance_prefix=partner.combatant_id,
        )
        weapon_attack = float(partner.weapon["攻击"]) + max(
            0,
            int(partner.weapon["等级"]) - 1,
        ) * float(self.content.player["本命武器"]["每级攻击"])
        return CombatantSnapshot(
            id=partner.combatant_id,
            name=partner.npc_id,
            attributes=partner.attributes,
            level=partner.level,
            kind="道侣",
            weapon_attack=weapon_attack,
            techniques=tuple(loadout),
            health=partner.health,
            spirit=partner.spirit,
            shield=shield,
            statuses=tuple(partner.statuses),
            cooldowns=dict(cooldowns or {}),
            inventory=dict(inventory),
            auto_medicine=auto_medicine,
            medicine_threshold=medicine_threshold,
            skill_cursor=skill_cursor,
        )

    def apply_battle_results_in_connection(
        self,
        connection,
        user_id: str,
        results: tuple[CombatantResult, ...],
    ) -> None:
        by_id = {result.id: result for result in results}
        for partner in self.party_assets_in_connection(connection, user_id):
            result = by_id.get(partner.combatant_id)
            if result is None:
                raise RuntimeError(f"探险结算缺少道侣状态：{partner.npc_id}")
            partner.health = result.health
            partner.spirit = result.spirit
            partner.statuses = [value.to_dict() for value in result.statuses]
            self._update_partner_asset(connection, partner)

    def apply_exploration_states_in_connection(
        self,
        connection,
        user_id: str,
        states: list[dict[str, Any]],
    ) -> None:
        partners = {
            partner.npc_id: partner
            for partner in self.party_assets_in_connection(connection, user_id)
        }
        state_by_id = {str(value["npc_id"]): value for value in states}
        if set(partners) != set(state_by_id):
            raise RuntimeError("探险期间同行道侣发生变化，已拒绝覆盖")
        for npc_id, partner in partners.items():
            state = state_by_id[npc_id]
            expected_revision = int(state["revision"])
            if partner.revision != expected_revision:
                raise RuntimeError(f"探险期间道侣资产发生变化：{npc_id}")
            partner.health = float(state["health"])
            partner.spirit = float(state["spirit"])
            partner.stamina = float(state["stamina"])
            partner.statuses = [dict(value) for value in state.get("statuses") or ()]
            self._update_partner_asset(connection, partner)

    def settle_seclusion_in_connection(
        self,
        connection,
        user_id: str,
        *,
        experience: int,
        recovery_ratio: float,
        clear_statuses: bool,
    ) -> tuple[PartnerSeclusionResult, ...]:
        results: list[PartnerSeclusionResult] = []
        for partner in self.party_assets_in_connection(connection, user_id):
            applied, levels = self._gain_partner_experience(partner, experience)
            ratio = min(1.0, max(0.0, float(recovery_ratio)))
            recovered: dict[str, float] = {}
            for field_name, resource in (
                ("health", "血气"),
                ("spirit", "精神"),
                ("stamina", "体力"),
            ):
                current = float(getattr(partner, field_name))
                maximum = partner.resource_maximum(resource)
                value = min(maximum, current + (maximum - current) * ratio)
                setattr(partner, field_name, value)
                recovered[field_name] = value - current
            if clear_statuses:
                partner.statuses.clear()
            self._update_partner_asset(connection, partner)
            results.append(
                PartnerSeclusionResult(
                    partner.npc_id,
                    applied,
                    levels,
                    partner.level,
                    recovered["health"],
                    recovered["spirit"],
                    recovered["stamina"],
                )
            )
        return tuple(results)

    def gain_party_weapon_experience_in_connection(
        self,
        connection,
        user_id: str,
        amount: int,
        npc_ids: tuple[str, ...] | None = None,
    ) -> None:
        partners = self.party_assets_in_connection(connection, user_id)
        if npc_ids is not None:
            expected = set(npc_ids)
            partners = tuple(value for value in partners if value.npc_id in expected)
            if {value.npc_id for value in partners} != expected:
                raise RuntimeError("探险结算中的道侣已经不在当前队伍")
        for partner in partners:
            self._gain_partner_weapon_experience(partner, amount)
            self._update_partner_asset(connection, partner)

    def _ensure_partner_asset(
        self,
        connection,
        user_id: str,
        npc_id: str,
    ) -> PartnerAsset:
        row = connection.execute(
            "SELECT * FROM partner_assets WHERE user_id = ? AND npc_id = ?",
            (user_id, npc_id),
        ).fetchone()
        if row is not None:
            return _partner_asset(row)
        partner = self._generate_partner(user_id, npc_id, random.Random(int(self.seed_factory())))
        now = self.clock()
        connection.execute(
            """
            INSERT INTO partner_assets(
                user_id, npc_id, state_json, loadout_json,
                revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (
                user_id,
                npc_id,
                _json(_partner_state(partner)),
                _json(_partner_loadout(partner)),
                now,
                now,
            ),
        )
        return partner

    def _generate_partner(
        self,
        user_id: str,
        npc_id: str,
        rng: random.Random,
    ) -> PartnerAsset:
        definition = self.content.npc_definitions[npc_id]
        direction_id = str(definition["修行方向"])
        aptitude_min, aptitude_max = (int(value) for value in definition["资质范围"])
        aptitude = rng.randint(aptitude_min, aptitude_max)
        attributes = {str(key): float(value) for key, value in definition["属性"].items()}
        variation = definition["实力波动"]
        minimum, maximum = (int(value) for value in variation["倍率"])
        for key in variation["属性"]:
            attributes[str(key)] = round(
                attributes[str(key)] * rng.randint(minimum, maximum) / 100,
                4,
            )

        limits = self.content.player["道侣"]
        candidates = self.content.npc_loadout_candidates(npc_id)
        slot_count = int(limits["功法位"])
        rolled = roll_loadout(
            self.content,
            rng,
            candidates=candidates,
            counts={
                "功法": slot_count,
                "附魔": int(limits["附魔位"]),
                "宝石": int(limits["宝石位"]),
            },
            direction_id=direction_id,
        )
        weapon_rules = self.content.player["本命武器"]
        return PartnerAsset(
            user_id=user_id,
            npc_id=npc_id,
            direction_id=direction_id,
            aptitude=aptitude,
            level=1,
            experience=0,
            attributes=attributes,
            health=float(attributes["血气上限"]),
            spirit=float(attributes["精神上限"]),
            stamina=float(attributes["体力上限"]),
            statuses=[],
            weapon={
                "名称": f"{npc_id}的本命武器",
                "等级": int(weapon_rules["初始等级"]),
                "经验": 0,
                "攻击": float(weapon_rules["基础攻击"]),
            },
            techniques=[dict(value) for value in rolled.techniques],
            enchantments=[dict(value) for value in rolled.enchantments],
            gems=[dict(value) for value in rolled.gems],
        )

    def _gain_partner_experience(self, partner: PartnerAsset, amount: int) -> tuple[int, int]:
        pending = max(0, int(amount))
        applied = 0
        levels = 0
        rules = self.content.player["人物"]
        maximum_level = int(rules["等级上限"])
        definition = self.content.npc_definitions[partner.npc_id]
        low, high = (int(value) for value in definition["资质范围"])
        ratio = 1.0 if high <= low else (partner.aptitude - low) / (high - low)
        growth_multiplier = 0.75 + max(0.0, min(1.0, ratio)) * 0.5
        while pending > 0 and partner.level < maximum_level:
            required = self.player.experience_required(partner.level)
            accepted = min(pending, required - partner.experience)
            partner.experience += accepted
            applied += accepted
            pending -= accepted
            if partner.experience < required:
                break
            partner.experience = 0
            partner.level += 1
            levels += 1
            for key, growth in dict(rules["每级成长"]).items():
                partner.attributes[str(key)] = partner.attributes.get(str(key), 0.0) + (
                    float(growth) * growth_multiplier
                )
        return applied, levels

    def _gain_partner_weapon_experience(self, partner: PartnerAsset, amount: int) -> None:
        pending = max(0, int(amount))
        maximum_level = int(self.content.player["本命武器"]["等级上限"])
        while pending > 0 and int(partner.weapon["等级"]) < maximum_level:
            level = int(partner.weapon["等级"])
            required = self.player.weapon_experience_required(level)
            accepted = min(pending, required - int(partner.weapon["经验"]))
            partner.weapon["经验"] = int(partner.weapon["经验"]) + accepted
            pending -= accepted
            if int(partner.weapon["经验"]) < required:
                break
            partner.weapon["经验"] = 0
            partner.weapon["等级"] = level + 1

    def _update_partner_asset(self, connection, partner: PartnerAsset) -> None:
        cursor = connection.execute(
            """
            UPDATE partner_assets SET
                state_json = ?, loadout_json = ?, revision = revision + 1,
                updated_at = ?
            WHERE user_id = ? AND npc_id = ? AND revision = ?
            """,
            (
                _json(_partner_state(partner)),
                _json(_partner_loadout(partner)),
                self.clock(),
                partner.user_id,
                partner.npc_id,
                partner.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"道侣状态已变化，拒绝覆盖：{partner.npc_id}")
        partner.revision += 1

    def _is_nearby(self, npc_id: str, location_id: str, relation: Mapping | None) -> bool:
        return bool((relation or {}).get("in_party")) or self.home_locations[npc_id] == location_id

    @staticmethod
    def _relation(connection, user_id: str, npc_id: str) -> dict | None:
        row = connection.execute(
            """
            SELECT relations.favor, relations.reward_claimed, relations.in_party,
                   assets.state_json
            FROM partner_relations AS relations
            LEFT JOIN partner_assets AS assets
              ON assets.user_id = relations.user_id
             AND assets.npc_id = relations.npc_id
            WHERE relations.user_id = ? AND relations.npc_id = ?
            """,
            (user_id, npc_id),
        ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _relations(connection, user_id: str) -> dict[str, dict]:
        return {
            str(row["npc_id"]): dict(row)
            for row in connection.execute(
                """
                SELECT relations.npc_id, relations.favor,
                       relations.reward_claimed, relations.in_party,
                       assets.state_json
                FROM partner_relations AS relations
                LEFT JOIN partner_assets AS assets
                  ON assets.user_id = relations.user_id
                 AND assets.npc_id = relations.npc_id
                WHERE relations.user_id = ?
                """,
                (user_id,),
            )
        }

    def _save_relation(
        self,
        connection,
        user_id: str,
        npc_id: str,
        favor: int,
        reward_claimed: bool,
        in_party: bool,
    ) -> None:
        connection.execute(
            """
            INSERT INTO partner_relations(
                user_id, npc_id, favor, reward_claimed, in_party, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, npc_id) DO UPDATE SET
                favor = excluded.favor,
                reward_claimed = excluded.reward_claimed,
                in_party = excluded.in_party,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                npc_id,
                min(self.favor_max, max(0, int(favor))),
                int(bool(reward_claimed)),
                int(bool(in_party)),
                self.clock(),
            ),
        )


def _partner_state(partner: PartnerAsset) -> dict[str, Any]:
    return {
        "方向": partner.direction_id,
        "资质": partner.aptitude,
        "等级": partner.level,
        "经验": partner.experience,
        "属性": dict(partner.attributes),
        "血气": partner.health,
        "精神": partner.spirit,
        "体力": partner.stamina,
        "状态": [dict(value) for value in partner.statuses],
    }


def _partner_loadout(partner: PartnerAsset) -> dict[str, Any]:
    return {
        "本命武器": dict(partner.weapon),
        "功法": [dict(value) for value in partner.techniques],
        "附魔": [dict(value) for value in partner.enchantments],
        "宝石": [dict(value) for value in partner.gems],
    }


def _partner_asset(row: Mapping[str, Any]) -> PartnerAsset:
    state = json.loads(str(row["state_json"]))
    loadout = json.loads(str(row["loadout_json"]))
    if not isinstance(state, dict) or not isinstance(loadout, dict):
        raise ValueError("道侣资产数据损坏")
    return PartnerAsset(
        user_id=str(row["user_id"]),
        npc_id=str(row["npc_id"]),
        direction_id=str(state["方向"]),
        aptitude=int(state["资质"]),
        level=int(state["等级"]),
        experience=int(state["经验"]),
        attributes={str(key): float(value) for key, value in dict(state["属性"]).items()},
        health=float(state["血气"]),
        spirit=float(state["精神"]),
        stamina=float(state["体力"]),
        statuses=[dict(value) for value in state.get("状态") or ()],
        weapon=dict(loadout["本命武器"]),
        techniques=[dict(value) for value in loadout.get("功法") or ()],
        enchantments=[dict(value) for value in loadout.get("附魔") or ()],
        gems=[dict(value) for value in loadout.get("宝石") or ()],
        revision=int(row["revision"]),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "ALREADY_IN_PARTY",
    "FAVOR_FULL",
    "FAVOR_REQUIRED",
    "GIFTED",
    "INSUFFICIENT_ITEM",
    "INVALID_ITEM",
    "INVITED",
    "LEFT_PARTY",
    "NOT_IN_PARTY",
    "NOT_NEARBY",
    "NOT_PREFERRED",
    "GiftResult",
    "NpcFeature",
    "NpcProfile",
    "PartnerAsset",
    "PartnerSeclusionResult",
    "PartyResult",
    "SCHEMA",
]
