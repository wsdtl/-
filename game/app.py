"""游戏微服务的唯一组合根。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from launch import C, OnEvent, config, logger

from .config import game_config
from .core.combat import CombatService
from .core.data import JsonDataService
from .core.pool import PoolService


@dataclass(frozen=True)
class CoreServices:
    """全局基础微服务。"""

    data: JsonDataService
    combat: CombatService
    pool: PoolService


@dataclass(frozen=True)
class FeatureServices:
    """具体玩法微服务；后续按 JSON 契约逐项加入。"""


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
    core = CoreServices(data=data, combat=combat, pool=pool)
    features = FeatureServices()
    return GameServices(core=core, features=features)


_services: GameServices | None = None


@OnEvent.connect(priority=1100)
def migrate_legacy_runtime_storage() -> None:
    """首次重启时把旧运行文件迁出正式 JSON 数据目录。"""

    runtime_root = config.base_dir / ".runtime"
    migrations = (
        (config.base_dir / "data" / "game.db", game_config.database.path),
        (
            config.base_dir / "data" / "runtime_log.db",
            game_config.database.runtime_log_path,
        ),
        (config.base_dir / "data" / "backups", runtime_root / "backups"),
        (
            config.base_dir / "data" / "runtime_log_media",
            runtime_root / "runtime_log_media",
        ),
    )
    for source, target in migrations:
        if not source.exists() or source.resolve() == target.resolve():
            continue
        if target.exists():
            raise RuntimeError(f"运行文件迁移目标已经存在：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        logger.opt(colors=True).info(
            C.join(
                C.ok("运行文件已迁出 data"),
                C.kv("source", source),
                C.kv("target", target),
            )
        )


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
    _services = build_game_services()


@OnEvent.disconnect(priority=-1000)
def shutdown_game_services() -> None:
    """在具体玩法停止后释放本进程的游戏微服务集合。"""

    global _services
    _services = None


__all__ = [
    "CoreServices",
    "FeatureServices",
    "GameServices",
    "build_game_services",
    "current_game_services",
    "initialize_game_services",
    "migrate_legacy_runtime_storage",
    "shutdown_game_services",
]
