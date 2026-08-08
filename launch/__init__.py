"""应用框架公共入口。

业务层优先从这里导入配置、生命周期装饰器、调度器和日志工具；协议相关能力
从 launch.adapter 导入，避免公共入口被具体驱动器字段污染。
"""

from .allowed import FastAPIAllowed as FastAPIAllowed
from .config import config as config
from .lifespan import lifespan as lifespan
from .load_router import FastAPIIncludeRouter as FastAPIIncludeRouter
from .log import LOGGING_CONFIG as LOGGING_CONFIG
from .log import C as C
from .log import logger as logger
from .mount import FastAPIMount as FastAPIMount
from .on_event import OnEvent as OnEvent
from .schedulers import Scheduler as Scheduler
