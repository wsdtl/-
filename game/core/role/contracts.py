"""角色核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class RoleError(ValueError):
    """角色 JSON 无法形成一致角色档案。"""


@dataclass(frozen=True)
class RoleStatus:
    initialized: bool
    companion_count: int
    enemy_count: int
    growth_rule_count: int


@dataclass(frozen=True)
class RoleItemStack:
    identity: str
    quantity: int


@dataclass(frozen=True)
class RoleBuildSlot:
    section: str
    count: int
    file_ids: tuple[str, ...] = ()
    full_pool: bool = False


@dataclass(frozen=True)
class RoleProfile:
    identity: str
    name: str
    kind: str
    level: int
    qualification: int | None
    attributes: Mapping[str, float]
    resources: Mapping[str, float]
    weapon_attack: float
    build_slots: tuple[RoleBuildSlot, ...]
    inventory: tuple[RoleItemStack, ...] = ()
    auto_medicine: bool = False


__all__ = [
    "RoleBuildSlot",
    "RoleError",
    "RoleItemStack",
    "RoleProfile",
    "RoleStatus",
]
