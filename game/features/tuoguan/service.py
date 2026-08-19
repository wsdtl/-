"""托管玩法的业务入口与展示编排。"""

from __future__ import annotations

from game.core.data import JsonDataService
from game.core.hosting import HostingError, HostingService

from .contracts import HostingCopy, HostingFeatureError, HostingResult
from .presentation import load_presentation


class HostingFeature:
    def __init__(self, data: JsonDataService, hosting: HostingService) -> None:
        self._data = data
        self._hosting = hosting
        self._copy: HostingCopy | None = None

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("托管玩法微服务已经初始化")
        if not self._hosting.status().initialized:
            raise RuntimeError("托管核心必须先于托管玩法启动")
        self._copy = load_presentation(self._data)

    def copy(self) -> HostingCopy:
        if self._copy is None:
            raise RuntimeError("托管玩法微服务尚未初始化")
        return self._copy

    async def start(self, user_id: str, request_id: str) -> HostingResult:
        try:
            session = await self._hosting.start(user_id, request_id)
        except HostingError as exc:
            raise HostingFeatureError(exc.code) from exc
        return HostingResult("开启", session.mode, len(session.participant_user_ids))

    async def cancel(self, user_id: str, request_id: str) -> HostingResult:
        try:
            session = await self._hosting.cancel(user_id, request_id)
        except HostingError as exc:
            raise HostingFeatureError(exc.code) from exc
        return HostingResult("取消", session.mode, len(session.participant_user_ids))


__all__ = ["HostingFeature"]
