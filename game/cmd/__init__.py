"""命令与公共 HTTP 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from . import access_guard as access_guard
from .web import router as web_router

router = APIRouter()
router.include_router(web_router)


__all__ = ["router"]
