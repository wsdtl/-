"""从世界核心快照派生公开地图展示结果。"""

from __future__ import annotations

from game.core.world import WorldMapView, WorldService

from .contracts import WorldMapOverview


class WorldMapFeature:
    """统一供应地图页面快照与地图命令概况。"""

    def __init__(self, world: WorldService) -> None:
        self._world = world
        self._snapshot: WorldMapView | None = None
        self._overview: WorldMapOverview | None = None

    def initialize(self) -> WorldMapOverview:
        if self._snapshot is not None:
            raise RuntimeError("公开地图玩法微服务已经初始化")
        if not self._world.status().initialized:
            raise RuntimeError("世界地点微服务必须先于公开地图玩法启动")
        snapshot = self._world.map_view()
        overview = _overview(snapshot)
        self._snapshot = snapshot
        self._overview = overview
        return overview

    def overview(self) -> WorldMapOverview:
        if self._overview is None:
            raise RuntimeError("公开地图玩法微服务尚未初始化")
        return self._overview

    def snapshot(self) -> WorldMapView:
        if self._snapshot is None:
            raise RuntimeError("公开地图玩法微服务尚未初始化")
        return self._snapshot


def _overview(view: WorldMapView) -> WorldMapOverview:
    min_x, max_x, min_y, max_y = view.bounds
    return WorldMapOverview(
        name=view.name,
        description=view.description,
        width=max_x - min_x + 1,
        height=max_y - min_y + 1,
        region_count=len(view.regions),
        location_count=len(view.locations),
        road_count=len(view.roads),
    )


__all__ = ["WorldMapFeature"]
