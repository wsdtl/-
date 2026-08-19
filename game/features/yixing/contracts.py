from __future__ import annotations

from dataclasses import dataclass


class YixingError(ValueError):
    pass


class YixingConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class YixingResult:
    name: str
    gender_before: str
    gender_after: str
    medicine_name: str
    replayed: bool


__all__ = ["YixingConflictError", "YixingError", "YixingResult"]
