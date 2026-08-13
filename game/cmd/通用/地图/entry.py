"""公开地图命令回复。"""

from __future__ import annotations

from game.app import current_game_services
from game.features.ditu import WorldMapOverview
from launch.paths import public_url
from message import Action, DocumentMessage, M


async def show_entry(*, manager) -> None:
    overview = current_game_services().features.ditu.overview()
    await manager.send(_entry_message(overview, public_url("world-map")))


def _entry_message(overview: WorldMapOverview, url: str) -> DocumentMessage:
    reply = M.document().header(overview.name).section("全境舆图", icon="map")
    if overview.description:
        reply.line(overview.description)
    return (
        reply.row(
            ("范围", f"{overview.width} × {overview.height}"),
            ("区域", f"{overview.region_count}处"),
        )
        .row(
            ("地点", f"{overview.location_count}处"),
            ("道路", f"{overview.road_count}条"),
        )
        .line(M.link(f"打开{overview.name}地图", url))
        .action(Action("world_map.open", "打开地图", url, behavior="link"))
        .build()
    )


__all__ = ["show_entry"]
