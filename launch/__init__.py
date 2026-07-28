"""应用框架公共入口。

业务层优先从这里导入配置、生命周期装饰器、调度器和日志工具；协议相关能力
从 launch.adapter 导入，避免公共入口被具体驱动器字段污染。
"""

from .config import config as config
from .on_event import OnEvent as OnEvent
from .lifespan import lifespan as lifespan
from .schedulers import Scheduler as Scheduler
from .mount import FastAPIMount as FastAPIMount
from .allowed import FastAPIAllowed as FastAPIAllowed
from .load_router import FastAPIIncludeRouter as FastAPIIncludeRouter
from .log import C as C, LOGGING_CONFIG as LOGGING_CONFIG, logger as logger
