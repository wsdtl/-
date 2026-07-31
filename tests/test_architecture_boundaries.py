from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_removed_business_layer_cannot_return_as_source(self) -> None:
        game_root = ROOT / "game"
        forbidden: list[str] = []

        app_path = game_root / "app.py"
        if app_path.exists():
            forbidden.append(app_path.relative_to(ROOT).as_posix())

        features_root = game_root / "features"
        if features_root.exists():
            forbidden.extend(
                path.relative_to(ROOT).as_posix()
                for path in features_root.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            )

        self.assertEqual(
            sorted(forbidden),
            [],
            "不得恢复已经废弃的应用装配和玩法服务层",
        )

    def test_public_and_gameplay_commands_are_separate(self) -> None:
        command_root = ROOT / "game" / "cmd"
        public_root = ROOT / "game" / "public"
        example_env = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertFalse((command_root / "web").exists())
        self.assertTrue((public_root / "web" / "__init__.py").is_file())
        self.assertNotIn("game.public", (command_root / "__init__.py").read_text(encoding="utf-8"))
        self.assertIn(
            'ROUTER_GROUPS=["game.cmd","game.public"]',
            example_env,
        )

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
