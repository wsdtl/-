"""应用生命周期总编排。

启动顺序固定为：获取单实例锁、挂载资源与驱动器、启动驱动器、启动调度器、
执行业务回调；关闭时按相反职责清理。这里负责顺序，不包含任何业务规则。
"""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator, Callable, Iterable, List

if TYPE_CHECKING:
    from fastapi import FastAPI

from .log import C, logger
from .on_event import OnEvent
from .schedulers import Scheduler
from .mount import AdapterMount, FastAPIMount
from .runtime_guard import runtime_guard


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """FastAPI 生命周期。

    启动：挂载适配器、启动调度器、按优先级运行启动回调。
    关闭：按优先级运行关闭回调、关闭适配器、关闭调度器。
    """

    runtime_guard.acquire()
    adapters = []
    started = False

    try:
        adapters = await _mount_app(app)
        await _run_adapters(adapters)
        await _start_schedulers()
        await _add_scheduler_jobs()
        await _run_callbacks(OnEvent.ordered_callbacks(OnEvent.connect_list))
        started = True

        logger.opt(colors=True).success(f"{C.ok('FastAPI 服务启动成功')}")
        yield
    finally:
        callbacks = OnEvent.ordered_callbacks(OnEvent.disconnect_list) if started else []
        try:
            await _shutdown(callbacks, adapters)
        finally:
            runtime_guard.release()


async def _mount_app(app: FastAPI) -> List[type]:
    """挂载静态文件和 Adapter，并返回需要启动/关闭的 Adapter 列表。"""

    await FastAPIMount(app)
    return await AdapterMount(app)


async def _run_adapters(adapters: Iterable[type]) -> None:
    """启动 Adapter，让它们整理自己的运行期索引。"""

    for adapter in adapters:
        await adapter.run()


async def _start_schedulers() -> None:
    """启动同步和异步调度器。"""

    if not Scheduler.syncinstance.running:
        Scheduler.syncinstance.start()
    if not Scheduler.asyncinstance.running:
        Scheduler.asyncinstance.start()


async def _add_scheduler_jobs() -> None:
    """把装饰器收集到的定时任务添加到调度器。"""

    for task in Scheduler.sync_list:
        kwargs = task.get("kwargs", {})
        job_id = kwargs.get("id")
        if Scheduler.syncinstance.get_job(job_id):
            continue

        Scheduler.syncinstance.add_job(
            task.get("func"),
            *task.get("args", ()),
            **kwargs,
        )
        logger.opt(colors=True).success(
            C.join(
                C.ok("成功添加定时同步任务"),
                C.kv("id", job_id),
            )
        )

    for task in Scheduler.async_list:
        kwargs = task.get("kwargs", {})
        job_id = kwargs.get("id")
        if Scheduler.asyncinstance.get_job(job_id):
            continue

        Scheduler.asyncinstance.add_job(
            task.get("func"),
            *task.get("args", ()),
            **kwargs,
        )
        logger.opt(colors=True).success(
            C.join(
                C.ok("成功添加定时异步任务"),
                C.kv("id", job_id),
            )
        )


async def _run_callbacks(callbacks: Iterable[Callable]) -> None:
    """按传入顺序运行启动/关闭回调。"""

    for callback in callbacks:
        if inspect.iscoroutinefunction(callback):
            await callback()
        else:
            callback()


async def _shutdown(callbacks: Iterable[Callable], adapters: Iterable[type]) -> None:
    """关闭阶段统一清理资源。"""

    try:
        await _run_callbacks(callbacks)
    finally:
        await _shutdown_adapters(adapters)
        await _shutdown_schedulers()


async def _shutdown_adapters(adapters: Iterable[type]) -> None:
    """通知 Adapter 清理自己的后台任务和连接。"""

    for adapter in adapters:
        shutdown = getattr(adapter, "shutdown", None)
        if shutdown is None:
            continue

        result = shutdown()
        if inspect.isawaitable(result):
            await result


async def _shutdown_schedulers() -> None:
    """关闭调度器，避免热重载或退出时留下后台线程/任务。"""

    if Scheduler.syncinstance.running:
        Scheduler.syncinstance.shutdown(wait=False)
    if Scheduler.asyncinstance.running:
        Scheduler.asyncinstance.shutdown(wait=False)
