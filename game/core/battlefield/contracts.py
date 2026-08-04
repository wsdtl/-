"""战场环境微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class BattlefieldError(ValueError):
    """地点、秘境或战场环境不能形成合法战场。"""


@dataclass(frozen=True)
class BattlefieldEnvironment:
    identity: str
    name: str
    stages: tuple[str, ...]


@dataclass(frozen=True)
class BattlefieldStatus:
    initialized: bool
    environment_count: int
    surface_terrain_count: int
    default_realm_environment: str


__all__ = [
    "BattlefieldEnvironment",
    "BattlefieldError",
    "BattlefieldStatus",
]
