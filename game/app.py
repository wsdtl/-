"""游戏微服务的唯一组合根。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from launch import C, OnEvent, config, logger

from .config import game_config
from .core.asset import AssetService
from .core.character import CharacterService
from .core.combat import CombatService
from .core.companion import CompanionService
from .core.data import JsonDataService
from .core.database import DatabaseService
from .core.enemy import EnemyService
from .core.exploration import ExplorationService
from .core.gathering import GatheringService
from .core.growth import GrowthService
from .core.item_catalog import ItemCatalogService
from .core.location import LocationService
from .core.player_state import PlayerStateService
from .core.pool import PoolService
from .core.retreat import RetreatService
from .core.team import TeamService
from .core.world import WorldService
from .features.biguan import RetreatFeature
from .features.caikuang import OreGatheringFeature
from .features.caiyao import HerbGatheringFeature
from .features.chakan_juese import CharacterOverviewFeature
from .features.chakan_wupin import ItemInspectionFeature
from .features.chuangjian_renwu import CreateCharacterFeature
from .features.daolv_jiejiao import CompanionInteractionFeature
from .features.daolv_peiyang import CompanionCultivationFeature
from .features.ditu import WorldMapFeature
from .features.duiwu import TeamFeature
from .features.najie import NajieFeature
from .features.renwu_peiyang import CharacterCultivationFeature
from .features.tanxian import ExplorationFeature
from .features.weizhi import PositionFeature
from .features.xinglu import TravelFeature
from .startup import validate_startup_contracts


@dataclass(frozen=True)
class CoreServices:
    """全局基础微服务。"""

    data: JsonDataService
    item_catalog: ItemCatalogService
    combat: CombatService
    pool: PoolService
    growth: GrowthService
    world: WorldService
    companion: CompanionService
    database: DatabaseService
    location: LocationService
    player_state: PlayerStateService
    team: TeamService
    character: CharacterService
    asset: AssetService
    enemy: EnemyService
    exploration: ExplorationService
    retreat: RetreatService
    gathering: GatheringService


@dataclass(frozen=True)
class FeatureServices:
    """具体玩法微服务；后续按 JSON 契约逐项加入。"""

    chuangjian_renwu: CreateCharacterFeature
    chakan_juese: CharacterOverviewFeature
    chakan_wupin: ItemInspectionFeature
    ditu: WorldMapFeature
    najie: NajieFeature
    weizhi: PositionFeature
    xinglu: TravelFeature
    daolv_jiejiao: CompanionInteractionFeature
    renwu_peiyang: CharacterCultivationFeature
    daolv_peiyang: CompanionCultivationFeature
    tanxian: ExplorationFeature
    duiwu: TeamFeature
    biguan: RetreatFeature
    caiyao: HerbGatheringFeature
    caikuang: OreGatheringFeature


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
    growth = GrowthService(data, pool)
    growth_status = growth.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("角色成长核心微服务已启动"),
            C.kv("realms", growth_status.realm_count),
            C.kv("max_level", growth_status.maximum_level),
            C.kv("weapon_max_level", growth_status.weapon_maximum_level),
        )
    )
    world = WorldService(data)
    world_status = world.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("世界地点服务已启动"),
            C.kv("locations", world_status.location_count),
            C.kv("regions", world_status.region_count),
            C.kv("roads", world_status.road_count),
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
            C.kv("locations", database_status.location_count),
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
    team = TeamService(data, database, player_state)
    team_status = team.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("队伍核心微服务已启动"),
            C.kv("maximum_players", team_status.maximum_players),
            C.kv("invitation_seconds", team_status.invitation_seconds),
        )
    )
    location = LocationService(data, database, world)
    location_status = location.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("玩家位置核心微服务已启动"),
            C.kv("players", location_status.player_count),
            C.kv("radius", location_status.nearby_radius_meters),
            C.kv("page_size", location_status.nearby_page_size),
        )
    )
    companion = CompanionService(data, database, growth)
    companion_status = companion.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("世界道侣核心微服务已启动"),
            C.kv("companions", companion_status.companion_count),
            C.kv("locations", companion_status.location_count),
        )
    )
    asset = AssetService(data, database)
    asset_status = asset.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("玩家资产核心微服务已启动"),
            C.kv("categories", asset_status.category_count),
            C.kv("subcategories", asset_status.subcategory_count),
            C.kv("page_limit", asset_status.page_limit),
        )
    )
    character = CharacterService(
        data, database, player_state, location, asset, growth
    )
    character_service_status = character.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("角色核心微服务已启动"),
            C.kv("role", character_service_status.role_name),
            C.kv("genders", character_service_status.gender_count),
            C.kv("initial_items", character_service_status.initial_item_count),
        )
    )
    enemy = EnemyService(data, pool, growth, asset)
    enemy_status = enemy.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("敌人实例核心微服务已启动"),
            C.kv("enemies", enemy_status.enemy_count),
        )
    )
    exploration = ExplorationService(
        data,
        database,
        world,
        location,
        character,
        companion,
        asset,
        player_state,
        enemy,
        combat,
    )
    exploration_status = exploration.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("普通探险核心微服务已启动"),
            C.kv("seconds_per_battle", exploration_status.seconds_per_battle),
            C.kv("maximum_battles", exploration_status.maximum_battles),
        )
    )
    retreat = RetreatService(
        data,
        database,
        world,
        location,
        character,
        companion,
        asset,
        player_state,
        pool,
    )
    retreat_status = retreat.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("闭关核心微服务已启动"),
            C.kv("seconds_per_round", retreat_status.seconds_per_round),
            C.kv("maximum_rounds", retreat_status.maximum_rounds),
        )
    )
    gathering = GatheringService(
        data,
        database,
        world,
        location,
        character,
        companion,
        asset,
        player_state,
        pool,
    )
    gathering_status = gathering.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("采集核心微服务已启动"),
            C.kv("modes", len(gathering_status.modes)),
        )
    )
    core = CoreServices(
        data=data,
        item_catalog=item_catalog,
        combat=combat,
        pool=pool,
        growth=growth,
        world=world,
        companion=companion,
        database=database,
        location=location,
        player_state=player_state,
        team=team,
        character=character,
        asset=asset,
        enemy=enemy,
        exploration=exploration,
        retreat=retreat,
        gathering=gathering,
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
    chakan_juese = CharacterOverviewFeature(character, player_state, world, location)
    chakan_juese.initialize()
    ditu = WorldMapFeature(world)
    map_overview = ditu.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("公开地图玩法微服务已启动"),
            C.kv("regions", map_overview.region_count),
            C.kv("locations", map_overview.location_count),
            C.kv("roads", map_overview.road_count),
        )
    )
    najie = NajieFeature(asset)
    najie.initialize()
    weizhi = PositionFeature(
        data,
        world,
        location,
        character,
        player_state,
        companion,
        team,
    )
    weizhi.initialize()
    xinglu = TravelFeature(world, character, location, team)
    xinglu.initialize()
    daolv_jiejiao = CompanionInteractionFeature(
        data,
        companion,
        item_catalog,
        asset,
        character,
        location,
        world,
        database,
    )
    daolv_jiejiao.initialize()
    renwu_peiyang = CharacterCultivationFeature(
        data,
        character,
        asset,
        item_catalog,
        growth,
        database,
    )
    renwu_peiyang.initialize()
    daolv_peiyang = CompanionCultivationFeature(
        data,
        companion,
        asset,
        item_catalog,
        growth,
        database,
    )
    daolv_peiyang.initialize()
    duiwu = TeamFeature(data, team, character, location, player_state)
    duiwu.initialize()
    tanxian = ExplorationFeature(data, exploration, item_catalog, asset, team)
    tanxian.initialize()
    biguan = RetreatFeature(data, retreat, asset, team)
    biguan.initialize()
    caiyao = HerbGatheringFeature(data, gathering, asset, team)
    caiyao.initialize()
    caikuang = OreGatheringFeature(data, gathering, asset, team)
    caikuang.initialize()
    features = FeatureServices(
        chuangjian_renwu=create_character,
        chakan_juese=chakan_juese,
        chakan_wupin=chakan_wupin,
        ditu=ditu,
        najie=najie,
        weizhi=weizhi,
        xinglu=xinglu,
        daolv_jiejiao=daolv_jiejiao,
        renwu_peiyang=renwu_peiyang,
        daolv_peiyang=daolv_peiyang,
        tanxian=tanxian,
        duiwu=duiwu,
        biguan=biguan,
        caiyao=caiyao,
        caikuang=caikuang,
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

    services = build_game_services()
    try:
        validate_startup_contracts(services.core)
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
