"""托管核心微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class HostingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class HostingServiceStatus:
    initialized: bool
    control_states: Mapping[str, str]


@dataclass(frozen=True)
class HostingSession:
    session_id: str
    mode: str
    leader_user_id: str
    participant_user_ids: tuple[str, ...]


__all__ = ["HostingError", "HostingServiceStatus", "HostingSession"]
