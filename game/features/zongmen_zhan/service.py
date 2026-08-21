from __future__ import annotations

from collections.abc import Mapping

from game.core.sect_war import SectWarError, SectWarService, SectWarView


class SectWarFeature:
    def __init__(self, data, war: SectWarService) -> None:
        self._data, self._war, self._initialized = data, war, False
        self._text = {}
    def initialize(self) -> None:
        if self._initialized: raise RuntimeError("宗门战玩法已经初始化")
        if not self._war.status().initialized: raise RuntimeError("宗门战核心必须先于玩法微服务启动")
        raw = self._data.dataset("宗门战展示").get("文本")
        if not isinstance(raw, Mapping):
            raise TypeError("宗门战展示文本缺失")
        self._text = {
            str(section): {str(key): str(value) for key, value in values.items()}
            for section, values in raw.items()
            if isinstance(values, Mapping)
        }
        self._initialized = True
    async def challenge(self, user_id, target, wager, request_id): return await self._war.challenge(user_id, target, wager, request_id)
    async def accept(self, user_id, war_id, request_id): return await self._war.accept(user_id, war_id, request_id)
    async def lock(self, user_id, war_id, request_id): return await self._war.lock(user_id, war_id, request_id)
    async def start(self, user_id, war_id, request_id): return await self._war.start(user_id, war_id, request_id)
    async def view(self, war_id): return await self._war.view(war_id)
    async def settle(self, user_id, war_id, request_id): return await self._war.settle(user_id, war_id, request_id)

    def text(self, section: str, key: str, **values: object) -> str:
        try:
            template = self._text[section][key]
        except KeyError as exc:
            raise RuntimeError(f"宗门战展示缺少文本：{section}.{key}") from exc
        return template.format(**values)

__all__ = ["SectWarError", "SectWarFeature", "SectWarView"]
