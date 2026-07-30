"""人物、本命武器、纳戒与功法实例的唯一资产事务服务。"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from typing import Any

from game.content import GameContent
from game.core import Database, inverse_weighted_choice, require_user_id, utc_now
from game.rules.loadout import compatibility_issues

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
    grade_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (user_id, item_id, grade_id)
);

CREATE TABLE IF NOT EXISTS techniques (
    instance_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    technique_id TEXT NOT NULL,
    grade_id TEXT NOT NULL,
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
        self._migrate_inventory_stacks()

    def _migrate_inventory_stacks(self) -> None:
        """把旧的无品级库存原子迁移为最低品级，不丢现有资产。"""

        with self.database.transaction(write=True) as connection:
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(inventory_stacks)")
            }
            if "grade_id" in columns:
                return
            base_grade = self.lowest_grade_id
            connection.execute(
                "ALTER TABLE inventory_stacks RENAME TO inventory_stacks_legacy"
            )
            connection.execute(
                """
                CREATE TABLE inventory_stacks (
                    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL,
                    grade_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity >= 0),
                    PRIMARY KEY (user_id, item_id, grade_id)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO inventory_stacks(user_id, item_id, grade_id, quantity)
                SELECT user_id, item_id, ?, quantity
                FROM inventory_stacks_legacy
                WHERE quantity > 0
                """,
                (base_grade,),
            )
            connection.execute("DROP TABLE inventory_stacks_legacy")

    @property
    def lowest_grade_id(self) -> str:
        return min(
            self.content.grade_definitions,
            key=lambda grade_id: int(self.content.grade_definitions[grade_id]["阶序"]),
        )

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
            self.add_item_in_connection(
                connection,
                actor,
                str(item_id),
                int(quantity),
                self.lowest_grade_id,
            )

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
            self.item_name(str(row["item_id"]), str(row["grade_id"])): int(row["quantity"])
            for row in connection.execute(
                """
                SELECT item_id, grade_id, quantity
                FROM inventory_stacks
                WHERE user_id = ? AND quantity > 0
                """,
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
            grade = self.content.grade_definitions[instance.grade_id]
            result.append(
                {
                    "实例": instance.instance_id,
                    "功法": instance.technique_id,
                    "品级": instance.grade_id,
                    "出生序号": instance.born_order,
                    "威力倍率": float(grade["能力倍率"]),
                    "词条": [dict(value) for value in instance.affixes],
                    "能力": [dict(value) for value in definition.get("组成") or ()],
                }
            )
        return result

    def battle_loadout(self, assets: AssetState) -> list[dict[str, Any]]:
        issues = self._loadout_issues(assets.techniques, assets.weapon)
        if issues:
            raise ValueError("当前战斗构筑不合法：" + "；".join(issues))
        result = self.battle_techniques(assets.techniques)
        for kind, values in (
            ("附魔", assets.weapon.enchantments),
            ("宝石", assets.weapon.gems),
        ):
            for index, value in enumerate(values, start=1):
                result.append(
                    self.content.configured_weapon_augment(
                        kind,
                        str(value["名称"]),
                        str(value["品级"]),
                        instance_id=f"player:{assets.player.user_id}:{kind}:{index}",
                    )
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

    def add_item_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        item_id: str,
        quantity: int,
        grade_id: str | None = None,
    ) -> None:
        amount = int(quantity)
        if amount < 1:
            return
        item_key = str(item_id)
        grade_key = str(grade_id or self.lowest_grade_id)
        if item_key not in self.content.item_definitions:
            raise ValueError(f"未知物品：{item_key}")
        if grade_key not in self.content.grade_definitions:
            raise ValueError(f"未知品级：{grade_key}")
        connection.execute(
            """
            INSERT INTO inventory_stacks(user_id, item_id, grade_id, quantity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, item_id, grade_id)
            DO UPDATE SET quantity = quantity + excluded.quantity
            """,
            (user_id, item_key, grade_key, amount),
        )

    def remove_item_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        item_id: str,
        quantity: int,
        grade_id: str | None = None,
    ) -> bool:
        return self.take_item_in_connection(
            connection,
            user_id,
            item_id,
            quantity,
            grade_id,
        ) is not None

    def take_item_in_connection(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        item_id: str,
        quantity: int,
        grade_id: str | None = None,
    ) -> dict[str, int] | None:
        """按低品级优先扣除物品，并返回实际扣除的完整品级名称。"""

        amount = max(1, int(quantity))
        item_key = str(item_id)
        rows = list(
            connection.execute(
                """
                SELECT grade_id, quantity
                FROM inventory_stacks
                WHERE user_id = ? AND item_id = ? AND quantity > 0
                """
                + (" AND grade_id = ?" if grade_id is not None else ""),
                (user_id, item_key, str(grade_id))
                if grade_id is not None
                else (user_id, item_key),
            )
        )
        rows.sort(
            key=lambda row: int(self.content.grade_definitions[str(row["grade_id"])]["阶序"])
        )
        if sum(int(row["quantity"]) for row in rows) < amount:
            return None
        remaining = amount
        taken: dict[str, int] = {}
        for row in rows:
            if remaining <= 0:
                break
            consumed = min(remaining, int(row["quantity"]))
            row_grade = str(row["grade_id"])
            connection.execute(
                """
                UPDATE inventory_stacks
                SET quantity = quantity - ?
                WHERE user_id = ? AND item_id = ? AND grade_id = ?
                """,
                (consumed, user_id, item_key, row_grade),
            )
            taken[self.item_name(item_key, row_grade)] = consumed
            remaining -= consumed
        connection.execute(
            """
            DELETE FROM inventory_stacks
            WHERE user_id = ? AND item_id = ? AND quantity = 0
            """,
            (user_id, item_key),
        )
        return taken

    @staticmethod
    def item_name(item_id: str, grade_id: str) -> str:
        return f"{grade_id}·{item_id}"

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

    def _weapon_progress(self, weapon: WeaponState) -> int:
        initial_level = int(self.content.player["本命武器"]["初始等级"])
        completed = sum(
            self.weapon_experience_required(level)
            for level in range(initial_level, int(weapon.level))
        )
        return completed + int(weapon.experience)

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
        technique_id = _weighted_choice(rng, self.content.technique_definitions)
        technique_definition = self.content.technique_definitions[technique_id]
        grade_id = _weighted_choice(rng, self.content.grade_definitions)
        grade = self.content.grade_definitions[grade_id]
        affix_pool = {
            affix_id: self.content.affix_definitions[affix_id]
            for affix_id in technique_definition["随机词条"]
        }
        affix_ids = _weighted_sample(
            rng,
            affix_pool,
            int(grade["词条数量"]),
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
        score = int(float(technique_definition["评分"]) * float(grade["能力倍率"]) + 0.5) + sum(
            _affix_score(value) for value in affixes
        )
        acquired_at = utc_now()
        connection.execute(
            """
            INSERT INTO techniques (
                instance_id, user_id, technique_id, grade_id,
                affixes_json, born_order, equipped_slot, score, acquired_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                instance_id,
                user_id,
                technique_id,
                grade_id,
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
            grade_id,
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
            techniques = self.techniques_in_connection(connection, actor)
            weapon = self.load_weapon_in_connection(connection, actor)
            current_issues = set(self._loadout_issues(techniques, weapon))
            projected = [
                value
                for value in techniques
                if value.instance_id != technique.instance_id
                and value.equipped_slot != target_slot
            ]
            projected.append(
                TechniqueState(
                    technique.instance_id,
                    technique.user_id,
                    technique.technique_id,
                    technique.grade_id,
                    technique.affixes,
                    technique.born_order,
                    target_slot,
                    technique.score,
                    technique.acquired_at,
                )
            )
            projected_issues = set(self._loadout_issues(projected, weapon))
            if projected_issues - current_issues:
                return "incompatible"
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
            techniques = self.techniques_in_connection(connection, actor)
            target = next(
                (value for value in techniques if value.equipped_slot == int(slot)),
                None,
            )
            if target is None:
                return "empty_slot"
            weapon = self.load_weapon_in_connection(connection, actor)
            current_issues = set(self._loadout_issues(techniques, weapon))
            projected = [
                value for value in techniques if value.instance_id != target.instance_id
            ]
            projected_issues = set(self._loadout_issues(projected, weapon))
            if projected_issues - current_issues:
                return "incompatible"
            cursor = connection.execute(
                "UPDATE techniques SET equipped_slot = NULL WHERE user_id = ? AND equipped_slot = ?",
                (actor, int(slot)),
            )
        return "unequipped" if cursor.rowcount else "empty_slot"

    def _loadout_issues(
        self,
        techniques: list[TechniqueState],
        weapon: WeaponState,
    ) -> tuple[str, ...]:
        selected = {
            "功法": tuple(
                (
                    value.technique_id,
                    self.content.technique_definitions[value.technique_id],
                )
                for value in techniques
                if value.equipped_slot is not None
            ),
            "附魔": tuple(
                (
                    str(value["名称"]),
                    self.content.enchantment_definitions[str(value["名称"])],
                )
                for value in weapon.enchantments
            ),
            "宝石": tuple(
                (
                    str(value["名称"]),
                    self.content.gem_definitions[str(value["名称"])],
                )
                for value in weapon.gems
            ),
        }
        return compatibility_issues(selected)

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
        resolved = self.resolve_item(item_name)
        if resolved is None:
            return ItemUseResult("not_found")
        item_id, requested_grade = resolved
        display_name = (
            self.item_name(item_id, requested_grade)
            if requested_grade is not None
            else item_id
        )
        use = self.content.item_definitions[item_id].get("使用效果")
        if not isinstance(use, dict):
            return ItemUseResult("not_usable", display_name)
        effect_type = str(use.get("类型") or "")
        if effect_type == "增加道侣经验":
            return ItemUseResult(
                "partner_required",
                display_name,
                effect=effect_type,
            )

        requested_count = max(1, int(quantity))
        with self.database.transaction(write=True) as connection:
            player = self.load_player_in_connection(connection, actor)
            if effect_type == "增加人物经验":
                if player.breakthrough_pending or player.level >= int(
                    self.content.player["人物"]["等级上限"]
                ):
                    return ItemUseResult(
                        "progress_locked",
                        display_name,
                        effect=effect_type,
                        target=player.name,
                    )
                taken = self.take_item_in_connection(
                    connection,
                    actor,
                    item_id,
                    requested_count,
                    requested_grade,
                )
                if taken is None:
                    return ItemUseResult("insufficient", display_name)
                gained = self.gain_experience(
                    player,
                    int(use["经验"]) * requested_count,
                )
                self.update_player_in_connection(
                    connection,
                    player,
                    expected_revision=player.revision,
                )
                return ItemUseResult(
                    "used",
                    display_name,
                    requested_count,
                    effect=effect_type,
                    experience=gained.applied,
                    levels_gained=gained.levels_gained,
                    target=player.name,
                )

            if effect_type == "增加本命武器经验":
                weapon = self.load_weapon_in_connection(connection, actor)
                if weapon.level >= int(self.content.player["本命武器"]["等级上限"]):
                    return ItemUseResult(
                        "progress_locked",
                        display_name,
                        effect=effect_type,
                        target=weapon.name,
                    )
                taken = self.take_item_in_connection(
                    connection,
                    actor,
                    item_id,
                    requested_count,
                    requested_grade,
                )
                if taken is None:
                    return ItemUseResult("insufficient", display_name)
                before = self._weapon_progress(weapon)
                levels = self.gain_weapon_experience(
                    weapon,
                    int(use["经验"]) * requested_count,
                )
                applied = self._weapon_progress(weapon) - before
                self.update_weapon_in_connection(connection, weapon)
                return ItemUseResult(
                    "used",
                    display_name,
                    requested_count,
                    effect=effect_type,
                    experience=applied,
                    levels_gained=levels,
                    target=weapon.name,
                )

            rows = list(
                connection.execute(
                    """
                    SELECT grade_id, quantity
                    FROM inventory_stacks
                    WHERE user_id = ? AND item_id = ? AND quantity > 0
                    """
                    + (" AND grade_id = ?" if requested_grade is not None else ""),
                    (actor, item_id, requested_grade)
                    if requested_grade is not None
                    else (actor, item_id),
                )
            )
            rows.sort(
                key=lambda row: int(
                    self.content.grade_definitions[str(row["grade_id"])]["阶序"]
                )
            )
            if not rows:
                return ItemUseResult("insufficient", display_name)
            if effect_type == "恢复血气":
                resource_field = "health"
                resource_name = "血气"
            elif effect_type == "恢复精神":
                resource_field = "spirit"
                resource_name = "精神"
            else:
                return ItemUseResult("not_usable", display_name)
            maximum = player.resource_maximum(resource_name)
            current = float(getattr(player, resource_field))
            if current >= maximum:
                return ItemUseResult("already_full", display_name, resource=resource_name)
            used = 0
            recovered = 0.0
            for row in rows:
                if used >= requested_count or current >= maximum:
                    break
                grade_id = str(row["grade_id"])
                graded = self.content.graded_item_definition(item_id, grade_id)
                per_item = float(graded["使用效果"]["恢复量"])
                needed = max(1, math.ceil((maximum - current) / per_item))
                count = min(int(row["quantity"]), requested_count - used, needed)
                applied = min(maximum - current, per_item * count)
                connection.execute(
                    """
                    UPDATE inventory_stacks
                    SET quantity = quantity - ?
                    WHERE user_id = ? AND item_id = ? AND grade_id = ?
                    """,
                    (count, actor, item_id, grade_id),
                )
                used += count
                recovered += applied
                current += applied
            connection.execute(
                """
                DELETE FROM inventory_stacks
                WHERE user_id = ? AND item_id = ? AND quantity = 0
                """,
                (actor, item_id),
            )
            setattr(player, resource_field, current)
            self.update_player_in_connection(
                connection,
                player,
                expected_revision=player.revision,
            )
        return ItemUseResult(
            "used",
            display_name,
            used,
            recovered,
            resource_name,
            effect=effect_type,
        )

    def resolve_item(self, value: str) -> tuple[str, str | None] | None:
        text = str(value or "").strip()
        if text in self.content.item_definitions:
            return text, None
        for grade_id in self.content.grade_definitions:
            prefix = f"{grade_id}·"
            if text.startswith(prefix):
                item_id = text[len(prefix) :]
                if item_id in self.content.item_definitions:
                    return item_id, grade_id
        return None

    def inventory_categories(self, user_id: str) -> tuple[tuple[str, str, int], ...]:
        actor = require_user_id(user_id)
        with self.database.transaction() as connection:
            counts = {key: 0 for key in self.content.item_categories}
            for row in connection.execute(
                """
                SELECT item_id, grade_id, quantity
                FROM inventory_stacks
                WHERE user_id = ? AND quantity > 0
                """,
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
                    """
                    SELECT item_id, grade_id, quantity
                    FROM inventory_stacks
                    WHERE user_id = ? AND quantity > 0
                    """,
                    (actor,),
                ):
                    item_id = str(row["item_id"])
                    definition = self.content.item_definitions.get(item_id)
                    if definition is None or definition.get("类别") != category_id:
                        continue
                    grade_id = str(row["grade_id"])
                    graded = self.content.graded_item_definition(item_id, grade_id)
                    entries.append(
                        InventoryEntry(
                            category=category_id,
                            key=item_id,
                            name=str(graded["名称"]),
                            quantity=int(row["quantity"]),
                            score=int(graded["评分"]),
                            detail=str(graded.get("说明") or ""),
                            grade_id=grade_id,
                            reference_price=int(graded["参考价"]),
                        )
                    )
                entries.sort(
                    key=lambda value: (
                        -int(self.content.grade_definitions[value.grade_id]["阶序"]),
                        -value.score,
                        value.name,
                    )
                )
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
            category="功法",
            key=str(value.born_order),
            name=f"{value.grade_id}·{value.technique_id}",
            quantity=1,
            score=value.score,
            detail=affixes,
            grade_id=value.grade_id,
            equipped_slot=value.equipped_slot,
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
        grade_id=str(row["grade_id"]),
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
    return str(inverse_weighted_choice(rng, ids, weights))


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
