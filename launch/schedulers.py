"""同步与异步定时任务注册表。

装饰器只收集任务定义，lifespan 在调度器启动后统一安装。每项任务必须有稳定
id，以便重复创建应用或热重载时去重。
"""

from typing import Callable, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.background import BackgroundScheduler

from .config import config


def _get_scheduler_timezone() -> ZoneInfo:
    """读取项目时区，避免 APScheduler 自动探测系统时区。"""

    try:
        return ZoneInfo(config.project.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"PROJECT_TIMEZONE 配置无效，当前值是：{config.project.timezone}") from exc


SCHEDULER_TIMEZONE = _get_scheduler_timezone()


class Scheduler:
    """定时任务注册器。"""

    syncinstance = BackgroundScheduler(timezone=SCHEDULER_TIMEZONE)
    sync_list: List[dict] = []
    asyncinstance = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
    async_list: List[dict] = []

    @staticmethod
    def _sync(*args, **kwargs) -> Callable:
        """注册同步定时任务。

        必须传入 id，方便热重载去重和日志定位。

            @Scheduler._sync("interval", seconds=10, id="sync_user_cache")
            def sync_user_cache():
                ...
        """

        def wrapper(func: Callable):
            Scheduler._check_job_id(func, kwargs)
            Scheduler.sync_list.append(
                {
                    "func": func,
                    "args": args,
                    "kwargs": kwargs,
                }
            )
            return func

        return wrapper

    @staticmethod
    def _async(*args, **kwargs) -> Callable:
        """注册异步定时任务。

        必须传入 id，方便热重载去重和日志定位。

            @Scheduler._async("interval", minutes=3, id="swjk_historydata")
            async def swjk_historydata():
                ...
        """

        def wrapper(func: Callable):
            Scheduler._check_job_id(func, kwargs)
            Scheduler.async_list.append(
                {
                    "func": func,
                    "args": args,
                    "kwargs": kwargs,
                }
            )
            return func

        return wrapper

    @staticmethod
    def _check_job_id(func: Callable, kwargs: dict) -> None:
        """检查定时任务是否传入 id。"""

        if kwargs.get("id"):
            return

        raise ValueError(
            f"定时任务 {func.__module__}.{func.__name__} 必须传入 id，例如："
            f' @Scheduler._async("interval", minutes=3, id="{func.__name__}")'
        )
