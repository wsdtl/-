from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOTS = (PROJECT_ROOT / "game", PROJECT_ROOT / "launch")
DYNAMIC_IMPORT_LOADERS = frozenset(
    {
        "game/cmd/__init__.py",
        "launch/load_router.py",
    }
)


def test_companion_interaction_keeps_its_specific_component_boundary() -> None:
    generic_component = PROJECT_ROOT / "game" / "cmd" / "专属" / "道侣"
    interaction_component = PROJECT_ROOT / "game" / "cmd" / "专属" / "道侣结交"

    assert not generic_component.exists(), "道侣结交与道侣培养不得重新合并为笼统组件"
    assert (interaction_component / "__init__.py").is_file()


def test_command_components_use_init_as_the_callback_entry() -> None:
    violations: list[str] = []
    command_root = PROJECT_ROOT / "game" / "cmd"
    for scope in ("通用", "专属", "后台"):
        scope_root = command_root / scope
        for component in sorted(path for path in scope_root.iterdir() if path.is_dir()):
            if component.name == "__pycache__":
                continue
            init_path = component / "__init__.py"
            if not init_path.is_file():
                violations.append(
                    f"{component.relative_to(PROJECT_ROOT)} 缺少 __init__.py"
                )
            handlers_path = component / "handlers.py"
            if handlers_path.exists():
                violations.append(
                    f"{handlers_path.relative_to(PROJECT_ROOT)} 不应建立第二个回调入口"
                )
    assert violations == [], "命令二级组件目录不符合约定：\n" + "\n".join(violations)


def test_game_commands_are_declared_only_in_handler_modules() -> None:
    violations: list[str] = []
    command_root = PROJECT_ROOT / "game" / "cmd"
    for path in command_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        if (
            any(_is_game_command_decorator(node) for node in ast.walk(tree))
            and path.name != "__init__.py"
        ):
            violations.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert violations == [], "GameCommand 只能在组件 __init__.py 声明：\n" + "\n".join(
        violations
    )


def test_command_input_and_reply_modules_do_not_resolve_services() -> None:
    violations: list[str] = []
    command_root = PROJECT_ROOT / "game" / "cmd"
    for filename in ("input.py", "reply.py"):
        for path in command_root.rglob(filename):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "current_game_services":
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}"
                    )
    assert violations == [], "命令输入与回复模块不得取得游戏服务：\n" + "\n".join(
        violations
    )


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


def test_dynamic_imports_only_exist_in_designated_loaders() -> None:
    violations: list[str] = []
    for path in _runtime_files():
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        for line in _dynamic_import_lines(path):
            if relative not in DYNAMIC_IMPORT_LOADERS:
                violations.append(f"{relative}:{line}")
    assert violations == [], "动态导入只能存在于受控加载器：\n" + "\n".join(violations)


def test_runtime_does_not_use_assert_for_integrity_checks() -> None:
    violations: list[str] = []
    for path in _runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        violations.extend(
            f"{relative}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Assert)
        )
    assert violations == [], "运行时代码禁止使用 assert 承担完整性判断：\n" + "\n".join(
        violations
    )


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


def _dynamic_import_lines(path: Path) -> tuple[int, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    result: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in {"import_module", "__import__"}
        ) or (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
            and node.func.attr == "import_module"
        ):
            result.append(node.lineno)
    return tuple(result)


def _is_game_command_decorator(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    owner = node.func.value
    return (
        isinstance(owner, ast.Name)
        and owner.id == "GameCommand"
        and node.func.attr in {"fullmatch", "command", "regex"}
    )


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
        if _cross_feature_import(source, target):
            return "玩法组件不得互相导入，协作必须经过核心状态或组合根"
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


def _cross_feature_import(source: str, target: str) -> bool:
    if not target.startswith("game.features."):
        return False
    source_parts = source.split(".")
    target_parts = target.split(".")
    return len(source_parts) >= 3 and len(target_parts) >= 3 and source_parts[2] != target_parts[2]


def _is_internal_core_module(target: str) -> bool:
    return target.startswith("game.core.") and len(target.split(".")) > 3


def _is_within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")
