"""FastAPI 全局访问策略。

当前地基允许任意来源访问，便于本地调试和独立前端接入。正式开放管理接口前，
应在这里统一收紧来源，而不是让业务路由各自添加 CORS。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

if TYPE_CHECKING:
    from fastapi import FastAPI


def FastAPIAllowed(app: FastAPI) -> None:
    """配置跨域与公开 JSON 的统一压缩。"""

    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
