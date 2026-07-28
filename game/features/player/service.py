"""人物、本命武器、纳戒与功法实例的唯一资产事务服务。"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from typing import Any

from game.content import GameContent
from game.core import Database, rarity_weighted_choice, require_user_id, utc_now

from .models import (
    AssetState,
    ExperienceResult,
    InventoryEntry,
    InventoryPage,
    ItemUseResult,
    PlayerState,
    TechniqueState,
    WeaponState,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    experience INTEGER NOT NULL,
    attributes_json TEXT NOT NULL,
    health REAL NOT NULL,
    spirit REAL NOT NULL,
    stamina REAL NOT NULL,
    statuses_json TEXT NOT NULL,
    auto_medicine INTEGER NOT NULL,
    spirit_stones INTEGER NOT NULL,
    breakthrough_pending INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weapons (
    user_id TEXT PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    experience INTEGER NOT NULL,
    attributes_json TEXT NOT NULL,
    enchantments_json TEXT NOT NULL,
    gems_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_stacks (
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS techniques (
    instance_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    technique_id TEXT NOT NULL,
    rarity_id TEXT NOT NULL,
    affixes_json TEXT NOT NULL,
    born_order INTEGER NOT NULL,
    equipped_slot INTEGER CHECK (equipped_slot BETWEEN 1 AND 6),
    score INTEGER NOT NULL,
    acquired_at TEXT NOT NULL,
    UNIQUE (user_id, born_order),
    UNIQUE (user_id, equipped_slot)
);

CREATE INDEX IF NOT EXISTS ix_techniques_user_order
ON techniques(user_id, born_order);
"""

PAGE_SIZE = 50


class PlayerFeature:
    def __init__(self, database: Database, content: GameContent) -> None:
        self.database = database
        self.content = content

    def initialize(self) -> None:
        self.database.initialize(SCHEMA)

    def ensure(self, user_id: str, display_name: str = "") -> PlayerState:
        actor = require_user_id(user_id)
        with self.database.transaction(write=True) as connection:
            self.ensure_in_connection(connection, actor, display_name)
            return self.load_player_in_connection(connection, actor)

    def ensure_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        display_name: str = "",
    ) -> None:
        actor = require_user_id(user_id)
        if connection.execute(
            "SELECT 1 FROM players WHERE user_id = ?",
            (actor,),
        ).fetchone() is not None:
            return
        rules = self.content.player["人物"]
        weapon_rules = self.content.player["本命武器"]
        name = _display_name(display_name)
        attributes = {
            str(key): float(value)
            for key, value in dict(rules["属性"]).items()
        }
        now = utc_now()
        connection.execute(
            """
            INSERT INTO players (
                user_id, name, level, experience, attributes_json,
                health, spirit, stamina, statuses_json, auto_medicine,
                spirit_stones, breakthrough_pending, revision,
                created_at, updated_at
            ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, '[]', 1, ?, 0, 0, ?, ?)
            """,
            (
                actor,
                name,
                int(rules["初始等级"]),
                _json(attributes),
                attributes["血气上限"],
                attributes["精神上限"],
                attributes["体力上限"],
                int(rules["初始灵石"]),
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO weapons (
                user_id, name, level, experience, attributes_json,
                enchantments_json, gems_json
            ) VALUES (?, ?, ?, 0, ?, '[]', '[]')
            """,
            (
                actor,
                f"{name}的本命武器",
                int(weapon_rules["初始等级"]),
                _json({"攻击": float(weapon_rules["基础攻击"])}),
            ),
        )
        for item_id, quantity in dict(self.content.player.get("初始物品") or {}).items():
            self.add_item_in_connection(connection, actor, str(item_id), int(quantity))

    def load(self, user_id: str) -> AssetState:
        actor = require_user_id(user_id)
        with self.database.transaction() as connection:
            return self.load_assets_in_connection(connection, actor)

    def load_assets_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
    ) -> AssetState:
        actor = require_user_id(user_id)
        player = self.load_player_in_connection(connection, actor)
        weapon = self.load_weapon_in_connection(connection, actor)
        inventory = {
            str(row["item_id"]): int(row["quantity"])
            for row in connection.execute(
                "SELECT item_id, quantity FROM inventory_stacks WHERE user_id = ? AND quantity > 0",
                (actor,),
            )
        }
        techniques = self.techniques_in_connection(connection, actor)
        return AssetState(player, weapon, inventory, techniques)

    @staticmethod
    def load_player_in_connection(
        connection: sqlite3.Connection,
        user_id: str,
    ) -> PlayerState:
        row = connection.execute(
            "SELECT * FROM players WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"人物不存在：{user_id}")
        return _player(row)

    @staticmethod
    def load_weapon_in_connection(
        connection: sqlite3.Connection,
        user_id: str,
    ) -> WeaponState:
        row = connection.execute(
            "SELECT * FROM weapons WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"本命武器不存在：{user_id}")
        return _weapon(row)

    @staticmethod
    def techniques_in_connection(
        connection: sqlite3.Connection,
        user_id: str,
    ) -> list[TechniqueState]:
        return [
            _technique(row)
            for row in connection.execute(
                "SELECT * FROM techniques WHERE user_id = ? ORDER BY born_order",
                (user_id,),
            )
        ]

    def battle_techniques(self, techniques: list[TechniqueState]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for instance in sorted(
            (value for value in techniques if value.equipped_slot is not None),
            key=lambda value: value.born_order,
        ):
            definition = self.content.technique_definitions[instance.technique_id]
            rarity = self.content.rarity_definitions[instance.rarity_id]
            result.append(
                {
                    "实例": instance.instance_id,
                    "功法": instance.technique_id,
                    "品级": instance.rarity_id,
                    "出生序号": instance.born_order,
                    "威力倍率": float(rarity["威力倍率"]),
                    "词条": [dict(value) for value in instance.affixes],
                    "能力": [dict(value) for value in definition.get("组成") or ()],
                }
            )
        return result

    def update_player_in_connection(
        self,
        connection: sqlite3.Connection,
        player: PlayerState,
        *,
        expected_revision: int,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE players SET
                level = ?, experience = ?, attributes_json = ?,
                health = ?, spirit = ?, stamina = ?, statuses_json = ?,
                auto_medicine = ?, spirit_stones = ?, breakthrough_pending = ?,
                revision = revision + 1, updated_at = ?
            WHERE user_id = ? AND revision = ?
            """,
            (
                player.level,
                player.experience,
                _json(player.attributes),
                player.health,
                player.spirit,
                player.stamina,
                _json(player.statuses),
                int(player.auto_medicine),
                player.spirit_stones,
                int(player.breakthrough_pending),
                utc_now(),
                player.user_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("人物状态已变化，拒绝覆盖较新的资产")
        player.revision = expected_revision + 1

    @staticmethod
    def update_weapon_in_connection(
        connection: sqlite3.Connection,
        weapon: WeaponState,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE weapons SET
                name = ?, level = ?, experience = ?, attributes_json = ?,
                enchantments_json = ?, gems_json = ?
            WHERE user_id = ?
            """,
            (
                weapon.name,
                weapon.level,
                weapon.experience,
                _json(weapon.attributes),
                _json(weapon.enchantments),
                _json(weapon.gems),
                weapon.user_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("本命武器不存在")

    @staticmethod
    def add_item_in_connection(
        connection: sqlite3.Connection,
        user_id: str,
        item_id: str,
        quantity: int,
    ) -> None:
        amount = int(quantity)
        if amount < 1:
            return
        connection.execute(
            """
            INSERT INTO inventory_stacks(user_id, item_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, item_id)
            DO UPDATE SET quantity = quantity + excluded.quantity
            """,
            (user_id, item_id, amount),
        )

    @staticmethod
    def remove_item_in_connection(
        connection: sqlite3.Connection,
        user_id: str,
        item_id: str,
        quantity: int,
    ) -> bool:
        amount = max(1, int(quantity))
        cursor = connection.execute(
            """
            UPDATE inventory_stacks
            SET quantity = quantity - ?
            WHERE user_id = ? AND item_id = ? AND quantity >= ?
            """,
            (amount, user_id, item_id, amount),
        )
        if cursor.rowcount != 1:
            return False
        connection.execute(
            "DELETE FROM inventory_stacks WHERE user_id = ? AND item_id = ? AND quantity = 0",
            (user_id, item_id),
        )
        return True

    def gain_experience(self, player: PlayerState, amount: int) -> ExperienceResult:
        pending = max(0, int(amount))
        if pending == 0 or player.breakthrough_pending:
            return ExperienceResult(0, 0, player.breakthrough_pending)
        rules = self.content.player["人物"]
        maximum_level = int(rules["等级上限"])
        interval = max(1, int(rules["突破间隔"]))
        applied = 0
        levels = 0
        while pending > 0 and player.level < maximum_level:
            required = self.experience_required(player.level)
            accepted = min(pending, required - player.experience)
            player.experience += accepted
            applied += accepted
            pending -= accepted
            if player.experience < required:
                break
            player.experience = 0
            player.level += 1
            levels += 1
            for key, growth in dict(rules["每级成长"]).items():
                player.attributes[str(key)] = player.attributes.get(str(key), 0.0) + float(growth)
            if player.level % interval == 0:
                player.breakthrough_pending = True
                pending = 0
                break
        return ExperienceResult(applied, levels, player.breakthrough_pending)

    def experience_required(self, level: int) -> int:
        rule = self.content.player["人物"]["经验"]
        return int(rule["基础"]) + int(rule["等级平方系数"]) * int(level) ** 2

    def gain_weapon_experience(self, weapon: WeaponState, amount: int) -> int:
        pending = max(0, int(amount))
        gained = 0
        rules = self.content.player["本命武器"]
        maximum_level = int(rules["等级上限"])
        while pending > 0 and weapon.level < maximum_level:
            required = self.weapon_experience_required(weapon.level)
            accepted = min(pending, required - weapon.experience)
            weapon.experience += accepted
            pending -= accepted
            if weapon.experience < required:
                break
            weapon.experience = 0
            weapon.level += 1
            gained += 1
        return gained

    def weapon_experience_required(self, level: int) -> int:
        rule = self.content.player["本命武器"]["经验"]
        return int(rule["基础"]) + int(rule["等级平方系数"]) * int(level) ** 2

    def weapon_attack(self, weapon: WeaponState) -> float:
        rules = self.content.player["本命武器"]
        return float(weapon.attributes.get("攻击", rules["基础攻击"])) + (
            max(0, weapon.level - 1) * float(rules["每级攻击"])
        )

    def create_random_technique_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        rng: random.Random,
    ) -> TechniqueState:
        technique_id = rng.choice(tuple(self.content.technique_definitions))
        technique_definition = self.content.technique_definitions[technique_id]
        rarity_id = _weighted_choice(rng, self.content.rarity_definitions)
        rarity = self.content.rarity_definitions[rarity_id]
        affix_pool = {
            affix_id: self.content.affix_definitions[affix_id]
            for affix_id in technique_definition["随机词条"]
        }
        affix_ids = _weighted_sample(
            rng,
            affix_pool,
            int(rarity["词条数量"]),
        )
        affixes = tuple(
            _roll_affix(affix_id, affix_pool[affix_id], rng)
            for affix_id in affix_ids
        )
        born_order = int(
            connection.execute(
                "SELECT COALESCE(MAX(born_order), 0) + 1 FROM techniques WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        )
        instance_id = f"technique:{user_id}:{born_order}"
        score = int(rarity["评分"]) + sum(_affix_score(value) for value in affixes)
        acquired_at = utc_now()
        connection.execute(
            """
            INSERT INTO techniques (
                instance_id, user_id, technique_id, rarity_id,
                affixes_json, born_order, equipped_slot, score, acquired_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                instance_id,
                user_id,
                technique_id,
                rarity_id,
                _json(affixes),
                born_order,
                score,
                acquired_at,
            ),
        )
        return TechniqueState(
            instance_id,
            user_id,
            technique_id,
            rarity_id,
            affixes,
            born_order,
            None,
            score,
            acquired_at,
        )

    def equip_technique(self, user_id: str, born_order: int, slot: int) -> str:
        actor = require_user_id(user_id)
        target_slot = int(slot)
        if target_slot < 1 or target_slot > 6:
            return "invalid_slot"
        with self.database.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM techniques WHERE user_id = ? AND born_order = ?",
                (actor, int(born_order)),
            ).fetchone()
            if row is None:
                return "not_found"
            technique = _technique(row)
            duplicate = connection.execute(
                """
                SELECT 1 FROM techniques
                WHERE user_id = ? AND technique_id = ?
                  AND equipped_slot IS NOT NULL AND instance_id <> ?
                """,
                (actor, technique.technique_id, technique.instance_id),
            ).fetchone()
            if duplicate is not None:
                return "duplicate_name"
            connection.execute(
                "UPDATE techniques SET equipped_slot = NULL WHERE user_id = ? AND equipped_slot = ?",
                (actor, target_slot),
            )
            connection.execute(
                "UPDATE techniques SET equipped_slot = ? WHERE instance_id = ?",
                (target_slot, technique.instance_id),
            )
        return "equipped"

    def unequip_technique(self, user_id: str, slot: int) -> str:
        actor = require_user_id(user_id)
        with self.database.transaction(write=True) as connection:
            cursor = connection.execute(
                "UPDATE techniques SET equipped_slot = NULL WHERE user_id = ? AND equipped_slot = ?",
                (actor, int(slot)),
            )
        return "unequipped" if cursor.rowcount else "empty_slot"

    def set_auto_medicine(self, user_id: str, enabled: bool) -> PlayerState:
        actor = require_user_id(user_id)
        with self.database.transaction(write=True) as connection:
            player = self.load_player_in_connection(connection, actor)
            previous = player.revision
            player.auto_medicine = bool(enabled)
            self.update_player_in_connection(connection, player, expected_revision=previous)
            return player

    def use_item(self, user_id: str, item_name: str, quantity: int = 1) -> ItemUseResult:
        actor = require_user_id(user_id)
        item_id = self.resolve_item(item_name)
        if item_id is None:
            return ItemUseResult("not_found")
        definition = self.content.item_definitions[item_id]
        use = definition.get("使用效果")
        if not isinstance(use, dict):
            return ItemUseResult("not_usable", item_id)
        count = max(1, int(quantity))
        with self.database.transaction(write=True) as connection:
            player = self.load_player_in_connection(connection, actor)
            row = connection.execute(
                "SELECT quantity FROM inventory_stacks WHERE user_id = ? AND item_id = ?",
                (actor, item_id),
            ).fetchone()
            available = int(row["quantity"]) if row is not None else 0
            count = min(count, available)
            if count < 1:
                return ItemUseResult("insufficient", item_id)
            effect_type = str(use.get("类型") or "")
            if effect_type == "恢复血气":
                resource_field = "health"
                resource_name = "血气"
            elif effect_type == "恢复精神":
                resource_field = "spirit"
                resource_name = "精神"
            else:
                return ItemUseResult("not_usable", item_id)
            maximum = player.resource_maximum(resource_name)
            current = float(getattr(player, resource_field))
            if current >= maximum:
                return ItemUseResult("already_full", item_id, resource=resource_name)
            per_item = max(0.0, float(use.get("恢复量") or 0))
            needed = max(1, math.ceil((maximum - current) / per_item)) if per_item else 1
            count = min(count, needed)
            recovered = min(maximum - current, per_item * count)
            if not self.remove_item_in_connection(connection, actor, item_id, count):
                return ItemUseResult("insufficient", item_id)
            setattr(player, resource_field, current + recovered)
            previous = player.revision
            self.update_player_in_connection(connection, player, expected_revision=previous)
        return ItemUseResult(
            "used",
            item_id,
            count,
            recovered,
            resource_name,
        )

    def resolve_item(self, value: str) -> str | None:
        text = str(value or "").strip()
        return text if text in self.content.item_definitions else None

    def inventory_categories(self, user_id: str) -> tuple[tuple[str, str, int], ...]:
        actor = require_user_id(user_id)
        with self.database.transaction() as connection:
            counts = {key: 0 for key in self.content.item_categories}
            for row in connection.execute(
                "SELECT item_id, quantity FROM inventory_stacks WHERE user_id = ? AND quantity > 0",
                (actor,),
            ):
                definition = self.content.item_definitions.get(str(row["item_id"]))
                if definition is not None:
                    counts[str(definition["类别"])] += 1
            counts["功法"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM techniques WHERE user_id = ?",
                    (actor,),
                ).fetchone()[0]
            )
        return tuple(
            (category, category, counts.get(category, 0))
            for category in self.content.item_categories
        )

    def inventory_page(self, user_id: str, category: str, page: int = 1) -> InventoryPage:
        actor = require_user_id(user_id)
        category_id = str(category or "").strip()
        if category_id not in self.content.item_categories:
            raise ValueError(f"未知纳戒类别：{category_id}")
        requested_page = max(1, int(page))
        with self.database.transaction() as connection:
            if category_id == "功法":
                values = self.techniques_in_connection(connection, actor)
                entries = [self._technique_entry(value) for value in values]
            else:
                entries = []
                for row in connection.execute(
                    "SELECT item_id, quantity FROM inventory_stacks WHERE user_id = ? AND quantity > 0",
                    (actor,),
                ):
                    item_id = str(row["item_id"])
                    definition = self.content.item_definitions.get(item_id)
                    if definition is None or definition.get("类别") != category_id:
                        continue
                    entries.append(
                        InventoryEntry(
                            category_id,
                            item_id,
                            item_id,
                            int(row["quantity"]),
                            int(definition.get("评分") or 0),
                            str(definition.get("说明") or ""),
                        )
                    )
                entries.sort(key=lambda value: (-value.score, value.name, value.key))
        total = len(entries)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        current_page = min(requested_page, pages)
        start = (current_page - 1) * PAGE_SIZE
        return InventoryPage(
            category_id,
            category_id,
            current_page,
            pages,
            total,
            tuple(entries[start : start + PAGE_SIZE]),
        )

    def technique(self, user_id: str, born_order: int) -> TechniqueState | None:
        actor = require_user_id(user_id)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM techniques WHERE user_id = ? AND born_order = ?",
                (actor, int(born_order)),
            ).fetchone()
        return _technique(row) if row is not None else None

    def _technique_entry(self, value: TechniqueState) -> InventoryEntry:
        affixes = "、".join(str(item["词条"]) for item in value.affixes)
        return InventoryEntry(
            "功法",
            str(value.born_order),
            f"{value.rarity_id}·{value.technique_id}",
            1,
            value.score,
            affixes,
            value.equipped_slot,
        )


def _player(row: sqlite3.Row) -> PlayerState:
    return PlayerState(
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        level=int(row["level"]),
        experience=int(row["experience"]),
        attributes={
            str(key): float(value)
            for key, value in json.loads(str(row["attributes_json"])).items()
        },
        health=float(row["health"]),
        spirit=float(row["spirit"]),
        stamina=float(row["stamina"]),
        statuses=[dict(value) for value in json.loads(str(row["statuses_json"]))],
        auto_medicine=bool(row["auto_medicine"]),
        spirit_stones=int(row["spirit_stones"]),
        breakthrough_pending=bool(row["breakthrough_pending"]),
        revision=int(row["revision"]),
    )


def _weapon(row: sqlite3.Row) -> WeaponState:
    return WeaponState(
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        level=int(row["level"]),
        experience=int(row["experience"]),
        attributes={
            str(key): float(value)
            for key, value in json.loads(str(row["attributes_json"])).items()
        },
        enchantments=[dict(value) for value in json.loads(str(row["enchantments_json"]))],
        gems=[dict(value) for value in json.loads(str(row["gems_json"]))],
    )


def _technique(row: sqlite3.Row) -> TechniqueState:
    return TechniqueState(
        instance_id=str(row["instance_id"]),
        user_id=str(row["user_id"]),
        technique_id=str(row["technique_id"]),
        rarity_id=str(row["rarity_id"]),
        affixes=tuple(dict(value) for value in json.loads(str(row["affixes_json"]))),
        born_order=int(row["born_order"]),
        equipped_slot=int(row["equipped_slot"]) if row["equipped_slot"] is not None else None,
        score=int(row["score"]),
        acquired_at=str(row["acquired_at"]),
    )


def _weighted_choice(
    rng: random.Random,
    definitions: dict[str, dict[str, Any]],
) -> str:
    ids = tuple(definitions)
    weights = [int(definitions[key]["权重"]) for key in ids]
    return str(rarity_weighted_choice(rng, ids, weights))


def _weighted_sample(
    rng: random.Random,
    definitions: dict[str, dict[str, Any]],
    count: int,
) -> list[str]:
    remaining = dict(definitions)
    result: list[str] = []
    for _ in range(max(0, int(count))):
        selected = _weighted_choice(rng, remaining)
        result.append(selected)
        remaining.pop(selected)
        if not remaining:
            break
    return result


def _roll_affix(
    affix_id: str,
    definition: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    minimum = float(definition["最小值"])
    maximum = float(definition["最大值"])
    if minimum.is_integer() and maximum.is_integer():
        value: int | float = rng.randint(int(minimum), int(maximum))
    else:
        value = round(rng.uniform(minimum, maximum), 4)
    return {
        "词条": affix_id,
        "属性": str(definition["属性"]),
        "数值": value,
        "最小值": minimum,
        "最大值": maximum,
    }


def _affix_score(affix: dict[str, Any]) -> int:
    minimum = float(affix["最小值"])
    maximum = float(affix["最大值"])
    if maximum <= minimum:
        return 100
    ratio = (float(affix["数值"]) - minimum) / (maximum - minimum)
    return 60 + round(max(0.0, min(1.0, ratio)) * 60)


def _display_name(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:24] if text else "无名修士"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = ["PAGE_SIZE", "PlayerFeature", "SCHEMA"]
