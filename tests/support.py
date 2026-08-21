from __future__ import annotations

from game.core.data import JsonDataService
from game.core.database import DatabaseService
from game.core.innate_treasure import InnateTreasureService


def innate_treasure_service(
    data: JsonDataService, database: DatabaseService
) -> InnateTreasureService:
    service = InnateTreasureService(data, database)
    service.initialize()
    return service


__all__ = ["innate_treasure_service"]
