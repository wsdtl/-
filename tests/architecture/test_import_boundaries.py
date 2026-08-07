from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOTS = (PROJECT_ROOT / "game", PROJECT_ROOT / "launch")


def test_runtime_imports_respect_service_boundaries() -> None:
    violations: list[str] = []
    for path in _runtime_files():
        source = _module_name(path)
        for line, target in _imports(path, source):
            violation = _boundary_violation(source, target)
            if violation:
                relative = path.relative_to(PROJECT_ROOT).as_posix()
                violations.append(f"{relative}:{line} {violation}: {target}")

    assert violations == [], "运行时代码越过微服务边界：\n" + "\n".join(violations)


def _runtime_files() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for root in RUNTIME_ROOTS
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    )


def _module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path, source: str) -> tuple[tuple[int, str], ...]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    result: list[tuple[int, str]] = []
    package = source if path.name == "__init__.py" else source.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = _resolve_from_import(package, node)
            if target:
                result.append((node.lineno, target))
    return tuple(result)


def _resolve_from_import(package: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    parts = package.split(".") if package else []
    upward = node.level - 1
    if upward > len(parts):
        return ""
    if upward:
        parts = parts[:-upward]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _boundary_violation(source: str, target: str) -> str:
    if source == "launch" or source.startswith("launch."):
        if _is_within(target, "game") or _is_within(target, "tools"):
            return "框架层不得引用游戏层或维护工具"
        return ""

    if not _is_within(source, "game"):
        return ""
    if _is_within(target, "tools"):
        return "游戏运行时不得引用维护工具"

    if source == "game.core":
        if _is_within(target, "game.core") and target != "game.core":
            return "game.core 顶层不得转发具体核心服务"
        return ""

    if source.startswith("game.core."):
        if _is_within(target, "game.features") or _is_within(target, "game.cmd"):
            return "核心服务不得反向引用玩法或触发层"
        return _cross_core_violation(source, target)

    if source.startswith("game.features."):
        if _is_within(target, "game.cmd"):
            return "玩法服务不得反向引用触发层"
        if _is_internal_core_module(target):
            return "玩法服务只能从核心微服务包顶层导入"
        return ""

    if source.startswith("game.cmd.") and _is_within(target, "game.core"):
        return "触发层不得直接引用核心微服务"
    return ""


def _cross_core_violation(source: str, target: str) -> str:
    if not target.startswith("game.core."):
        return ""
    source_parts = source.split(".")
    target_parts = target.split(".")
    if len(source_parts) < 3 or len(target_parts) < 3:
        return ""
    if source_parts[2] != target_parts[2] and len(target_parts) > 3:
        return "跨核心服务只能从目标包顶层导入"
    return ""


def _is_internal_core_module(target: str) -> bool:
    return target.startswith("game.core.") and len(target.split(".")) > 3


def _is_within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")
