from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from game.core import JsonDataError, JsonDataReader, content_section
from game.content_loading import GameDataLoader


ROOT = Path(__file__).resolve().parents[1]


def _fields(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _fields(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _fields(nested)


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

    def test_formal_data_contains_no_balance_metadata(self) -> None:
        forbidden = {"评分", "评分模型", "职责", "随机词条"}
        catalog = JsonDataReader(ROOT / "data").load_catalog()
        for document in catalog.documents:
            for field in _fields(document.value):
                self.assertNotIn(field, forbidden, document.relative_path)

    def test_formal_json_uses_file_identity_without_redundant_root_keys(self) -> None:
        catalog = JsonDataReader(ROOT / "data").load_catalog()
        numbered = {"道侣", "物品", "功法", "附魔", "宝石", "机制"}
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

    def test_all_numbered_entity_kinds_share_the_same_identity_rule(self) -> None:
        cases = {
            "物品": ("100001", "物品"),
            "功法": ("400001", "功法"),
            "附魔": ("410001", "物品-附魔"),
            "宝石": ("420001", "物品-宝石"),
            "道侣": ("500001", "道侣"),
            "机制": ("600001", "机制"),
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
                second = dict(first)
                first_value = [first]
                second_value = [second]
                if section == "道侣":
                    first_file, second_file = "甲道侣.json", "乙道侣.json"
                elif section == "机制":
                    first_file, second_file = "机制甲.json", "机制乙.json"
                else:
                    first_file, second_file = f"{file_prefix}-甲.json", f"{file_prefix}-乙.json"
                directory = "战斗机制" if section == "机制" else section
                self._write(root / "内容" / directory / first_file, first_value)
                self._write(root / "内容" / directory / second_file, second_value)

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
    def test_staged_loader_indexes_clean_global_libraries(self) -> None:
        loaded = GameDataLoader(JsonDataReader(ROOT / "data")).load()

        self.assertEqual(len(loaded.entities["功法"]), 600)
        self.assertEqual(len(loaded.entities["附魔"]), 600)
        self.assertEqual(len(loaded.entities["宝石"]), 703)
        self.assertEqual(len(loaded.entities["机制"]), 1600)
        mechanism_pool = loaded.expand_pool(("主动攻伐",), "机制", deduplicate=True)
        self.assertEqual(len(mechanism_pool), 20)
        self.assertEqual(mechanism_pool[0][0], "600001")
        self.assertEqual(loaded.issues, ())

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

if __name__ == "__main__":
    unittest.main()
