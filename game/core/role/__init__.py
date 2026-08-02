"""人物、道侣、敌方修士与灵兽角色公共微服务。"""

from .contracts import RoleBuildSlot as RoleBuildSlot
from .contracts import RoleError as RoleError
from .contracts import RoleItemStack as RoleItemStack
from .contracts import RoleProfile as RoleProfile
from .contracts import RoleStatus as RoleStatus
from .service import RoleService as RoleService

__all__ = [
    "RoleBuildSlot",
    "RoleError",
    "RoleItemStack",
    "RoleProfile",
    "RoleService",
    "RoleStatus",
]
