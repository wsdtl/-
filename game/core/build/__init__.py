"""功法、附魔与宝石构筑生成公共微服务。"""

from .contracts import BuildError as BuildError
from .contracts import BuildRequest as BuildRequest
from .contracts import BuildResult as BuildResult
from .contracts import BuildSelection as BuildSelection
from .contracts import BuildSlotRequest as BuildSlotRequest
from .contracts import BuildStatus as BuildStatus
from .service import BuildService as BuildService

__all__ = [
    "BuildError",
    "BuildRequest",
    "BuildResult",
    "BuildSelection",
    "BuildService",
    "BuildSlotRequest",
    "BuildStatus",
]
