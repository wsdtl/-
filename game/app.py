"""游戏微服务的唯一组合根。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from launch import C, OnEvent, config, logger

from .config import game_config
from .core.character import CharacterService
from .core.combat import CombatService
from .core.data import JsonDataService
from .core.database import DatabaseService
from .core.item_catalog import ItemCatalogService
from .core.player_state import PlayerStateService
from .core.pool import PoolService
from .core.world import WorldService
from .features.chakan_juese import CharacterOverviewFeature
from .features.chakan_wupin import ItemInspectionFeature
from .features.chuangjian_renwu import CreateCharacterFeature


@dataclass(frozen=True)
class CoreServices:
    """全局基础微服务。"""

    data: JsonDataService
    item_catalog: ItemCatalogService
    combat: CombatService
    pool: PoolService
    world: WorldService
    database: DatabaseService
    player_state: PlayerStateService
    character: CharacterService


@dataclass(frozen=True)
class FeatureServices:
    """具体玩法微服务；后续按 JSON 契约逐项加入。"""

    chuangjian_renwu: CreateCharacterFeature
    chakan_juese: CharacterOverviewFeature
    chakan_wupin: ItemInspectionFeature


@dataclass(frozen=True)
class GameServices:
    """当前进程已经装配完成的游戏微服务。"""

    core: CoreServices
    features: FeatureServices


def build_game_services(*, data_dir: str | Path | None = None) -> GameServices:
    """按依赖顺序创建微服务；JSON 数据服务永远最先初始化。"""

    data = JsonDataService(data_dir or (config.base_dir / "data"))
    status = data.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("JSON 数据微服务已启动"),
            C.kv("documents", status.document_count),
            C.kv("entities", status.entity_count),
            C.kv("pools", status.pool_count),
        )
    )
    combat = CombatService(data)
    combat_status = combat.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("战斗核心微服务已启动"),
            C.kv("mechanisms", combat_status.mechanism_count),
            C.kv("abilities", combat_status.ability_count),
            C.kv("events", combat_status.event_count),
            C.kv("environments", combat_status.environment_count),
        )
    )
    item_catalog = ItemCatalogService(data)
    item_status = item_catalog.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("物品查询核心微服务已启动"),
            C.kv("items", item_status.item_count),
            C.kv("categories", len(item_status.category_counts)),
        )
    )
    pool = PoolService(data)
    pool_status = pool.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("资源池微服务已启动"),
            C.kv("modes", len(pool_status.modes)),
        )
    )
    world = WorldService(data)
    world_status = world.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("世界地点服务已启动"),
            C.kv("locations", world_status.location_count),
            C.kv("regions", world_status.region_count),
            C.kv("terrain_cells", world_status.terrain_cell_count),
        )
    )
    database = DatabaseService(
        game_config.database.path,
        busy_timeout_ms=game_config.database.busy_timeout_ms,
    )
    database_status = database.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("核心数据库微服务已启动"),
            C.kv("states", database_status.state_count),
            C.kv("transactions", database_status.transaction_count),
        )
    )
    player_state = PlayerStateService(data, database)
    player_state_status = player_state.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("人物状态核心微服务已启动"),
            C.kv("statuses", player_state_status.state_count),
            C.kv("guard_rules", player_state_status.guard_rule_count),
        )
    )
    character = CharacterService(data, database, player_state)
    character_service_status = character.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("角色核心微服务已启动"),
            C.kv("role", character_service_status.role_name),
            C.kv("genders", character_service_status.gender_count),
            C.kv("initial_items", character_service_status.initial_item_count),
        )
    )
    core = CoreServices(
        data=data,
        item_catalog=item_catalog,
        combat=combat,
        pool=pool,
        world=world,
        database=database,
        player_state=player_state,
        character=character,
    )
    create_character = CreateCharacterFeature(data, world, character)
    birthplace = create_character.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("创建人物玩法微服务已启动"),
            C.kv("birthplace", birthplace),
        )
    )
    chakan_wupin = ItemInspectionFeature(item_catalog)
    chakan_wupin.initialize()
    chakan_juese = CharacterOverviewFeature(character, player_state, world)
    chakan_juese.initialize()
    features = FeatureServices(
        chuangjian_renwu=create_character,
        chakan_juese=chakan_juese,
        chakan_wupin=chakan_wupin,
    )
    return GameServices(core=core, features=features)


_services: GameServices | None = None


def current_game_services() -> GameServices:
    """取得当前进程唯一的游戏微服务集合。"""

    if _services is None:
        raise RuntimeError("游戏微服务尚未初始化；请检查 game.app 启动注册")
    return _services


@OnEvent.connect(priority=1000)
def initialize_game_services() -> None:
    """在其他游戏入口运行前完成全部微服务装配。"""

    global _services
    if _services is not None:
        raise RuntimeError("游戏微服务已经初始化")
    from .cmd.access_guard import (
        register_game_access_guard,
        unregister_game_access_guard,
    )
    from .cmd.command import registered_guard_rules

    services = build_game_services()
    try:
        for rule_name in registered_guard_rules():
            services.core.player_state.validate_guard_rule(rule_name)
        register_game_access_guard()
    except Exception:
        unregister_game_access_guard()
        services.core.database.close()
        raise
    _services = services


@OnEvent.disconnect(priority=-1000)
def shutdown_game_services() -> None:
    """在具体玩法停止后释放本进程的游戏微服务集合。"""

    global _services
    from .cmd.access_guard import unregister_game_access_guard

    unregister_game_access_guard()
    if _services is not None:
        _services.core.database.close()
    _services = None


__all__ = [
    "CoreServices",
    "FeatureServices",
    "GameServices",
    "build_game_services",
    "current_game_services",
    "initialize_game_services",
    "shutdown_game_services",
]
