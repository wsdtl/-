"""FastAPI 资源和通信驱动器挂载。

静态资源与驱动器 HTTP 入口都在此统一接入应用。内部驱动器可以参与生命周期，
但没有 HTTP mount，例如本地驱动器不会暴露调试接口。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from fastapi import FastAPI

from .log import C, logger
from .adapter import BaseAdapter, enabled_adapter_specs
from .paths import STATIC_DIR


async def FastAPIMount(app: FastAPI) -> None:
    """挂载 FastAPI 全局资源。"""

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    if any(getattr(route, "path", "") == "/static" for route in app.routes):
        return

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


async def AdapterMount(app: FastAPI) -> list[type[BaseAdapter]]:
    """挂载通信适配器，并返回需要启动/关闭的处理器。"""

    adapters: list[type[BaseAdapter]] = []

    for spec in enabled_adapter_specs():
        mount = spec.http_mount
        if mount is not None and not any(getattr(route, "path", "") == mount.path for route in app.routes):
            app.include_router(mount.router)
            logger.opt(colors=True).success(
                f"{C.ok('已挂载适配器')} {C.kv('name', spec.name)} {C.kv('path', mount.path)}"
            )

        adapters.append(spec.handler)

    return adapters
