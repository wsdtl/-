from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from game.core import Database, JsonDataError, JsonDataReader, content_section
from game.content_loading import GameDataLoader
from game.features.didian import LocationFeature


ROOT = Path(__file__).resolve().parents[1]


class JsonDataReaderTests(unittest.TestCase):
    def test_catalog_registers_scopes_and_supports_both_pool_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._create_scopes(root)
            self._write(root / "定义" / "共同.json", {"值": "定义"})
            self._write(root / "规则" / "共同.json", {"值": "规则"})
            self._write(
                root / "内容" / "甲" / "物品-甲.json",
                [{"编号": "100001", "名称": "甲"}],
            )
            self._write(
                root / "内容" / "乙" / "物品-乙.json",
                [{"编号": "100001", "名称": "甲"}],
            )

            catalog = JsonDataReader(root).load_catalog()

            self.assertEqual(catalog.read("定义/共同.json"), {"值": "定义"})
            self.assertEqual(catalog.read("规则/共同"), {"值": "规则"})
            kept = catalog.expand_pool(("物品-甲", "物品-乙"), "物品", deduplicate=False)
            unique = catalog.expand_pool(("物品-甲", "物品-乙"), "物品", deduplicate=True)
            self.assertEqual([identity for identity, _ in kept], ["100001", "100001"])
            self.assertEqual([identity for identity, _ in unique], ["100001"])

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._create_scopes(root)
            path = root / "规则" / "重复.json"
            path.write_text('{"值": 1, "值": 2}', encoding="utf-8")

            with self.assertRaisesRegex(JsonDataError, "重复键：值"):
                JsonDataReader(root).load_catalog()

    def test_only_content_filenames_must_be_globally_unique(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._create_scopes(root)
            self._write(root / "定义" / "同名.json", {"值": 1})
            self._write(root / "规则" / "同名.json", {"值": 2})
            self._write(root / "内容" / "甲" / "同名.json", [])
            self._write(root / "内容" / "乙" / "同名.json", [])

            with self.assertRaisesRegex(JsonDataError, "内容文件名重复"):
                JsonDataReader(root).load_catalog()

    def test_score_metadata_is_rejected_from_formal_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._create_scopes(root)
            self._write(
                root / "内容" / "物品.json",
                [{"编号": "100001", "名称": "甲", "评分": 10}],
            )
            loaded = GameDataLoader(JsonDataReader(root)).load()

            self.assertTrue(
                any("评分 只能存在于 tools/战斗校验" in issue for issue in loaded.issues)
            )

    def test_formal_json_uses_file_identity_without_redundant_root_keys(self) -> None:
        catalog = JsonDataReader(ROOT / "data").load_catalog()
        numbered = {"道侣", "物品", "功法", "附魔", "宝石"}
        for document in catalog.documents:
            if document.scope != "内容":
                continue
            section = content_section(document)
            self.assertIsNotNone(section, document.relative_path)
            if section in numbered:
                self.assertIsInstance(document.value, list, document.relative_path)
            else:
                self.assertIsInstance(document.value, dict, document.relative_path)
                self.assertNotIn(section, document.value, document.relative_path)

        self.assertIsInstance(catalog.read("定义/品级.json"), list)
        self.assertNotIn("属性", catalog.read("定义/战斗/属性.json"))
        self.assertIn("品级编号规则", catalog.read("定义/编号.json"))
        self.assertFalse((ROOT / "data" / "校验").exists())
        checks = json.loads(
            (ROOT / "tools" / "战斗校验" / "内容完整性.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("参战者必需属性", checks)

    def test_all_numbered_entity_kinds_share_the_same_identity_rule(self) -> None:
        cases = {
            "物品": ("100001", "物品"),
            "功法": ("400001", "功法"),
            "附魔": ("410001", "物品-附魔"),
            "宝石": ("420001", "物品-宝石"),
            "道侣": ("500001", "道侣"),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._create_scopes(root)
            for section, (identity, file_prefix) in cases.items():
                first = {
                    "编号": identity,
                    "名称": f"同一{section}",
                    "说明": "甲池说明",
                    "权重": 10,
                    "实际属性": {"攻击": 1},
                }
                second = {
                    **first,
                    "说明": "乙池说明",
                    "权重": 20,
                }
                first_value = [first]
                second_value = [second]
                first_file = "甲道侣.json" if section == "道侣" else f"{file_prefix}-甲.json"
                second_file = "乙道侣.json" if section == "道侣" else f"{file_prefix}-乙.json"
                self._write(root / "内容" / section / first_file, first_value)
                self._write(root / "内容" / section / second_file, second_value)

            loaded = GameDataLoader(JsonDataReader(root)).load()

            self.assertFalse(any("用于不同" in issue for issue in loaded.issues))

    @staticmethod
    def _create_scopes(root: Path) -> None:
        for scope in ("定义", "规则", "内容", "展示"):
            (root / scope).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class ThreeAxisWorldTests(unittest.TestCase):
    def test_staged_loader_accepts_same_entities_in_multiple_pools(self) -> None:
        loaded = GameDataLoader(JsonDataReader(ROOT / "data")).load()

        self.assertEqual(len(loaded.catalog.documents), 1386)
        self.assertEqual(loaded.issues, ())
        loaded.require_valid()

    def test_all_registered_world_coordinates_use_z_zero(self) -> None:
        catalog = JsonDataReader(ROOT / "data").load_catalog()
        world = catalog.content_file("地图规则").value
        self.assertEqual(world["坐标边界"]["z轴"], [0, 0])

        regions = []
        locations = []
        for document in catalog.documents:
            if document.scope != "内容" or not isinstance(document.value, dict):
                continue
            section = content_section(document)
            if section == "区域":
                regions.append(document.value)
            elif section == "地点":
                locations.append(document.value)

        self.assertEqual(len(regions), 11)
        self.assertEqual(len(locations), 80)
        self.assertTrue(all(region["坐标范围"]["z轴"] == [0, 0] for region in regions))
        self.assertTrue(all(len(location["坐标"]) == 3 for location in locations))
        self.assertTrue(all(location["坐标"][2] == 0 for location in locations))
        self.assertEqual(len({tuple(location["坐标"]) for location in locations}), 80)

    def test_old_location_table_is_migrated_with_z_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "game.db")
            with database.transaction(write=True) as connection:
                connection.execute("CREATE TABLE players(user_id TEXT PRIMARY KEY)")
                connection.execute("INSERT INTO players(user_id) VALUES ('u1')")
                connection.execute(
                    """
                    CREATE TABLE player_locations (
                        user_id TEXT PRIMARY KEY REFERENCES players(user_id),
                        x INTEGER NOT NULL,
                        y INTEGER NOT NULL,
                        arrived_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO player_locations(user_id, x, y, arrived_at) "
                    "VALUES ('u1', 8, 8, '旧记录')"
                )

            feature = LocationFeature(database, _FakeContent(), _FakePlayer())
            feature.initialize()

            connection = sqlite3.connect(database.path)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(player_locations)")}
                row = connection.execute(
                    "SELECT x, y, z FROM player_locations WHERE user_id = 'u1'"
                ).fetchone()
            finally:
                connection.close()
            self.assertIn("z", columns)
            self.assertEqual(row, (8, 8, 0))
            self.assertEqual(feature.current("u1").coordinate_text, "(8, 8, 0)")


class _FakeContent:
    world_definition = {
        "名称": "测试世界",
        "说明": "测试",
        "出生地": "青溪村",
        "坐标边界": {"x轴": [0, 10], "y轴": [0, 10], "z轴": [0, 0]},
    }
    location_definitions = {
        "青溪村": {
            "坐标": [8, 8, 0],
            "地点类型": "村庄",
            "地形": "溪谷",
            "说明": "测试地点",
            "可用功能": [],
            "道侣池": [],
            "敌人池": [],
        }
    }

    @staticmethod
    def npcs_in_groups(groups: list[str]) -> tuple[str, ...]:
        return ()

    @staticmethod
    def enemies_in_groups(groups: list[str]) -> tuple[str, ...]:
        return ()


class _FakePlayer:
    @staticmethod
    def ensure_in_connection(connection, user_id: str, display_name: str = "") -> None:
        connection.execute("INSERT OR IGNORE INTO players(user_id) VALUES (?)", (user_id,))


if __name__ == "__main__":
    unittest.main()
