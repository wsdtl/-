"""JSON 微服务的公共导入边界回归测试。"""

from __future__ import annotations

import ast
from pathlib import Path

import game.core as core_namespace
import game.core.alchemy as alchemy_api
import game.core.battlefield as battlefield_api
import game.core.build as build_api
import game.core.combat as combat_api
import game.core.data as data_api
import game.core.forge as forge_api
import game.core.item as item_api
import game.core.pool as pool_api
import game.core.role as role_api
import game.core.travel as travel_api
import game.core.world as world_api

ROOT = Path(__file__).resolve().parents[1]
SERVICE_PACKAGES = (
    "game.core.combat",
    "game.core.battlefield",
    "game.core.data",
    "game.core.pool",
    "game.core.build",
    "game.core.world",
    "game.core.travel",
    "game.core.item",
    "game.core.forge",
    "game.core.alchemy",
    "game.core.role",
)


def test_core_namespace_does_not_forward_service_objects() -> None:
    assert core_namespace.__all__ == ["CORE_VERSION"]


def test_public_packages_only_export_stable_contracts_and_services() -> None:
    assert set(combat_api.__all__) == {
        "BattleEvent",
        "CombatBuildRef",
        "CombatFieldResult",
        "CombatFieldSpec",
        "CombatReportSpec",
        "CombatRequest",
        "CombatResult",
        "CombatService",
        "CombatStatus",
        "CombatStatusSpec",
        "CombatantResult",
        "CombatantReportSpec",
        "CombatantSpec",
        "StatusResult",
    }
    assert set(battlefield_api.__all__) == {
        "BattlefieldEnvironment",
        "BattlefieldError",
        "BattlefieldService",
        "BattlefieldStatus",
    }
    assert set(data_api.__all__) == {
        "JsonDataError",
        "JsonDataService",
        "JsonDataStatus",
        "JsonEntity",
        "JsonValue",
        "materialize",
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
    assert set(build_api.__all__) == {
        "BuildError",
        "BuildRequest",
        "BuildResult",
        "BuildSelection",
        "BuildService",
        "BuildSlotRequest",
        "BuildStatus",
    }
    assert set(world_api.__all__) == {
        "AltitudeRange",
        "LocationDefinition",
        "LocationFeatureDefinition",
        "LocationReference",
        "RegionDefinition",
        "RoadDefinition",
        "SurfaceBounds",
        "SurfaceCoordinate",
        "SurfacePoint",
        "WorldDataError",
        "WorldDefinition",
        "WorldService",
        "WorldStatus",
    }
    assert set(travel_api.__all__) == {
        "TravelError",
        "TravelMetrics",
        "TravelPlan",
        "TravelRequest",
        "TravelRealmEffects",
        "TravelService",
        "TravelStatus",
    }
    assert set(item_api.__all__) == {
        "ItemBattleState",
        "ItemCategory",
        "ItemDataError",
        "ItemDefinition",
        "ItemMedicineDefinition",
        "ItemService",
        "ItemStatus",
        "ItemUseEffect",
    }
    assert set(alchemy_api.__all__) == {
        "DIRECT_MODE",
        "SIDE_MODE",
        "AlchemyError",
        "AlchemyGradeBasis",
        "AlchemyMaterial",
        "AlchemyPlan",
        "AlchemyRequest",
        "AlchemyService",
        "AlchemyStatus",
        "FurnaceMethod",
        "MaterialAllocation",
        "PreparedBattlePills",
        "RecipeDefinition",
        "VeinRequirement",
    }
    assert set(forge_api.__all__) == {
        "DIRECT_MODE",
        "SIDE_MODE",
        "ForgeAllocation",
        "ForgeError",
        "ForgeLawDefinition",
        "ForgeMaterial",
        "ForgeMethod",
        "ForgePlan",
        "ForgeRequest",
        "ForgeService",
        "ForgeStatus",
        "ForgeVeinRequirement",
        "WeaponProfile",
        "WeaponState",
        "WeaponTier",
    }
    assert set(role_api.__all__) == {
        "RoleBuildSlot",
        "RoleError",
        "RoleItemStack",
        "RoleProfile",
        "RoleService",
        "RoleStatus",
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
                    cmd_violation = folder.name == "cmd" and module.startswith(
                        "game.core"
                    )
                    feature_violation = folder.name == "features" and (
                        module == "game.core"
                        or any(
                            module.startswith(f"{package}.")
                            for package in SERVICE_PACKAGES
                        )
                    )
                    if cmd_violation or feature_violation:
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno} -> {module}"
                        )
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
