"""控制台、战报等公共服务的触发入口。"""

from __future__ import annotations

from fastapi import APIRouter

from .web import router as web_router

router = APIRouter()
router.include_router(web_router)


__all__ = ["router"]
