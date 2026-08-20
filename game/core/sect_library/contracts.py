"""宗门藏经阁的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class SectLibraryError(RuntimeError):
    """藏经阁无法完成当前查询或借阅。"""


class SectLibraryConflictError(SectLibraryError):
    """借阅期间人物或宗门状态已经变化。"""


@dataclass(frozen=True)
class SectLibraryStatus:
    initialized: bool


@dataclass(frozen=True)
class SectTechnique:
    content_id: str
    name: str
    grade_id: str
    grade_name: str


@dataclass(frozen=True)
class SectLibraryView:
    sect_id: str
    techniques: tuple[SectTechnique, ...]


@dataclass(frozen=True)
class SectBorrowResult:
    slot: int
    technique: SectTechnique
    replayed: bool


__all__ = [
    "SectBorrowResult",
    "SectLibraryConflictError",
    "SectLibraryError",
    "SectLibraryStatus",
    "SectLibraryView",
    "SectTechnique",
]
