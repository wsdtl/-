"""宗门核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class SectError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SectConflictError(SectError):
    pass


@dataclass(frozen=True)
class SectServiceStatus:
    initialized: bool
    maximum_followers: int
    invitation_seconds: int


@dataclass(frozen=True)
class SectSnapshot:
    sect_id: str
    name: str
    leader_user_id: str
    cave_id: str
    entrance_xy: tuple[int, int]
    version: int


@dataclass(frozen=True)
class SectMember:
    sect_id: str
    user_id: str
    role: str
    join_order: int
    version: int


@dataclass(frozen=True)
class SectInvitation:
    sect_id: str
    sect_name: str
    inviter_user_id: str
    target_user_id: str
    expires_at: datetime
    version: int
    expired: bool


__all__ = [
    "SectConflictError",
    "SectError",
    "SectInvitation",
    "SectMember",
    "SectServiceStatus",
    "SectSnapshot",
]
