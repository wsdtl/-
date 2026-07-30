from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_game_never_imports_tools(self) -> None:
        violations: list[str] = []
        for path in sorted((ROOT / "game").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                else:
                    continue
                for module in modules:
                    if module == "tools" or module.startswith("tools."):
                        relative = path.relative_to(ROOT).as_posix()
                        violations.append(f"{relative}:{node.lineno} -> {module}")
        self.assertEqual(violations, [], "game 不得依赖游戏外工具")


if __name__ == "__main__":
    unittest.main()
