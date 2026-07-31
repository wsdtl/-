"""战斗机制已经脱离旧方向后的独立性守卫。"""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MechanismIndependenceTest(unittest.TestCase):
    def test_mechanisms_are_not_direction_copies(self) -> None:
        directory = ROOT / "data" / "内容" / "战斗机制"
        self.assertFalse((directory / "方向").exists())
        entries = [
            entry
            for path in sorted(directory.glob("*.json"))
            for entry in json.loads(path.read_text(encoding="utf-8"))
        ]

        def remove_display_names_and_numbers(value):
            if isinstance(value, dict):
                return {
                    key: remove_display_names_and_numbers(child)
                    for key, child in value.items()
                    if key != "名称"
                }
            if isinstance(value, list):
                return [remove_display_names_and_numbers(child) for child in value]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return "数值"
            return value

        fingerprints = {
            json.dumps(
                remove_display_names_and_numbers(entry["节点"]),
                ensure_ascii=False,
                sort_keys=True,
            )
            for entry in entries
        }
        self.assertEqual(len(entries), 1600)
        self.assertEqual(len(fingerprints), 1600)


if __name__ == "__main__":
    unittest.main()
