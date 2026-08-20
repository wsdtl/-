"""宗门资源生产入口编排与展示文本读取。"""

from __future__ import annotations

from collections.abc import Mapping

from game.core.data import JsonDataError, JsonDataService
from game.core.sect_production import SectProductionError, SectProductionService


class SectProductionFeatureError(RuntimeError):
    """宗门资源生产玩法无法完成当前请求。"""


class SectProductionFeature:
    def __init__(self, data: JsonDataService, production: SectProductionService) -> None:
        self._data = data
        self._production = production
        self._copy: Mapping[str, Mapping[str, str]] | None = None

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("宗门资源生产玩法已经初始化")
        raw = self._data.dataset("宗门生产展示").get("文本")
        if not isinstance(raw, Mapping):
            raise JsonDataError("宗门生产展示缺少文本.json")
        self._copy = raw

    def copy(self) -> Mapping[str, Mapping[str, str]]:
        if self._copy is None:
            raise RuntimeError("宗门资源生产玩法尚未初始化")
        return self._copy

    async def view(self, kind: str, user_id: str):
        try:
            return await self._production.view(kind, user_id)
        except SectProductionError as exc:
            raise SectProductionFeatureError(str(exc)) from exc

    async def collect(self, kind: str, user_id: str, request_id: str):
        try:
            return await self._production.collect(kind, user_id, request_id)
        except SectProductionError as exc:
            raise SectProductionFeatureError(str(exc)) from exc


__all__ = ["SectProductionFeature", "SectProductionFeatureError"]
