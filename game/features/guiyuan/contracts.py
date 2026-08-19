from __future__ import annotations

from dataclasses import dataclass


class GuiyuanError(ValueError):
    pass


class GuiyuanConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class GuiyuanPreview:
    location_name: str
    companion_name: str
    medicine_name: str
    has_medicine: bool
    counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class GuiyuanResult:
    companion_name: str
    category: str
    content_count: int
    medicine_name: str
    replayed: bool


__all__ = ["GuiyuanConflictError", "GuiyuanError", "GuiyuanPreview", "GuiyuanResult"]
