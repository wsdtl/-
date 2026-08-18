"""为战斗维护脚本组装隔离的正式核心依赖。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from game.core.asset import AssetService
from game.core.combat import CombatService
from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.formation import FormationService
from game.core.location import LocationService
from game.core.world import WorldService


@contextmanager
def isolated_combat_service(data: JsonDataService) -> Iterator[CombatService]:
    """使用临时数据库启动阵法与战斗核心，并在退出时释放资源。"""

    with TemporaryDirectory(prefix="xiaonan-combat-") as directory:
        world = WorldService(data)
        world.initialize()
        database = DatabaseService(Path(directory) / "game.db")
        database.initialize()
        try:
            location = LocationService(data, database, world)
            location.initialize()
            asset = AssetService(data, database)
            asset.initialize()
            formation = FormationService(data, database, asset, world, location)
            formation.initialize()
            combat = CombatService(data, formation)
            combat.initialize()
            yield combat
        finally:
            database.close()


__all__ = ["isolated_combat_service"]
