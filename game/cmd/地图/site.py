"""公开只读的晓楠修仙界地图页面与数据接口。"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

router = APIRouter(prefix="/world-map")
INDEX_HTML = static_path("world-map", "index.html")


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def world_map_page() -> HTMLResponse:
    return HTMLResponse(
        INDEX_HTML.read_text(encoding="utf-8"),
        headers=_page_headers(),
    )


@router.get("/data", response_class=JSONResponse)
async def world_map_data() -> JSONResponse:
    snapshot = current_game_services().features.ditu.snapshot()
    return JSONResponse(asdict(snapshot), headers=_data_headers())


def _page_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
    }


def _data_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }


__all__ = ["router"]
