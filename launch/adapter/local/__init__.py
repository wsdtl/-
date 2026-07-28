"""本地命令驱动器包导出。"""

from __future__ import annotations

from .event import LocalCommandEvent as LocalCommandEvent
from .event import local_command_event as local_command_event
from .handler import LocalCommandMatch as LocalCommandMatch
from .handler import LocalCommandRule as LocalCommandRule
from .handler import LocalEventHandler as LocalEventHandler
from .manager import LocalDispatchResult as LocalDispatchResult
from .manager import LocalReply as LocalReply
from .manager import current_event as current_event
from .manager import manager as manager


async def dispatch(*args, **kwargs) -> LocalDispatchResult:
    """通过本地驱动器分发一条命令。"""

    return await LocalEventHandler.dispatch(*args, **kwargs)
