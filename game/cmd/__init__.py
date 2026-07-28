"""游戏二级组件与 Web 路由总入口。"""

from __future__ import annotations

from fastapi import APIRouter

from .web import router as web_router

router = APIRouter()
router.include_router(web_router)


__all__ = ["router"]
