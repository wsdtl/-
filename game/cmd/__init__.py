"""具体玩法命令路由组。"""

from __future__ import annotations

from fastapi import APIRouter

from .public import router as public_router


router = APIRouter()
router.include_router(public_router)


__all__ = ["router"]
