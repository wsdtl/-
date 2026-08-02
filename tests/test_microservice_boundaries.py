"""JSON 微服务的公共导入边界回归测试。"""

from __future__ import annotations

import ast
from pathlib import Path

import game.core as core_namespace
import game.core.combat as combat_api
import game.core.data as data_api
import game.core.pool as pool_api

ROOT = Path(__file__).resolve().parents[1]
SERVICE_PACKAGES = (
    "game.core.combat",
    "game.core.data",
    "game.core.pool",
)


def test_core_namespace_does_not_forward_service_objects() -> None:
    assert core_namespace.__all__ == ["CORE_VERSION"]


def test_public_packages_only_export_stable_contracts_and_services() -> None:
    assert set(combat_api.__all__) == {
        "BattleEvent",
        "CombatBuildRef",
        "CombatReportSpec",
        "CombatRequest",
        "CombatResult",
        "CombatService",
        "CombatStatus",
        "CombatantResult",
        "CombatantReportSpec",
        "CombatantSpec",
        "StatusResult",
    }
    assert set(data_api.__all__) == {
        "JsonDataError",
        "JsonDataService",
        "JsonDataStatus",
    }
    assert set(pool_api.__all__) == {
        "ALLOW_REPEATS",
        "EXPAND_DEDUPLICATED",
        "PoolEntry",
        "PoolRequest",
        "PoolResult",
        "PoolService",
        "PoolStatus",
    }
    assert not hasattr(data_api.JsonDataService, "read")
    assert not hasattr(data_api.JsonDataService, "scope")


def test_runtime_business_does_not_import_core_internals() -> None:
    violations: list[str] = []
    for folder in (ROOT / "game" / "cmd", ROOT / "game" / "features"):
        for path in folder.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                for module in _imported_modules(node):
                    if folder.name == "cmd" and module.startswith("game.core"):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno} -> {module}")
                    elif folder.name == "features" and (
                        module == "game.core"
                        or any(module.startswith(f"{package}.") for package in SERVICE_PACKAGES)
                    ):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno} -> {module}")
    assert violations == []


def test_core_services_only_use_other_services_public_packages() -> None:
    violations: list[str] = []
    for owner in SERVICE_PACKAGES:
        folder = ROOT.joinpath(*owner.split("."))
        for path in folder.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                for module in _imported_modules(node):
                    for dependency in SERVICE_PACKAGES:
                        if dependency == owner:
                            continue
                        if module.startswith(f"{dependency}."):
                            violations.append(
                                f"{path.relative_to(ROOT)}:{node.lineno} -> {module}"
                            )
    assert violations == []


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.ImportFrom):
        return (node.module or "",)
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    return ()
