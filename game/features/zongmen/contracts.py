"""宗门玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class SectFeatureError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SectAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class SectMemberView:
    user_id: str
    name: str
    role: str


@dataclass(frozen=True)
class SectPage:
    page: str
    name: str = ""
    leader_name: str = ""
    entrance: str = ""
    cave_id: str = ""
    members: tuple[SectMemberView, ...] = ()
    invitation_name: str = ""
    invitation_inviter_name: str = ""
    invitation_minutes: int = 0


@dataclass(frozen=True)
class SectOperationResult:
    action: str
    target_name: str
    page: SectPage


@dataclass(frozen=True)
class SectCopy:
    text: Mapping[str, Mapping[str, str]]


__all__ = [
    "SectAction",
    "SectCopy",
    "SectFeatureError",
    "SectMemberView",
    "SectOperationResult",
    "SectPage",
]
