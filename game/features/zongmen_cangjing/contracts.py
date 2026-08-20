"""宗门藏经阁玩法的稳定结果。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.sect_library import SectBorrowResult, SectTechnique


class CangjingFeatureError(RuntimeError):
    """当前玩家无法完成藏经阁操作。"""


@dataclass(frozen=True)
class CangjingAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class CangjingPage:
    page: int
    page_count: int
    total_entries: int
    entries: tuple[SectTechnique, ...]


@dataclass(frozen=True)
class CangjingCopy:
    text: Mapping[str, str]


__all__ = [
    "CangjingAction",
    "CangjingCopy",
    "CangjingFeatureError",
    "CangjingPage",
    "SectBorrowResult",
]
