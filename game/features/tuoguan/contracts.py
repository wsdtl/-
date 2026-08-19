"""托管玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class HostingFeatureError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class HostingCopy:
    text: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class HostingResult:
    action: str
    mode: str
    participant_count: int


__all__ = ["HostingCopy", "HostingFeatureError", "HostingResult"]
