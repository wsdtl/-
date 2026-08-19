from __future__ import annotations

from dataclasses import dataclass


class ButianError(ValueError):
    pass


class ButianConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class ButianResult:
    target: str
    target_name: str
    realm_name: str
    attribute: str
    value: int | float
    medicine_name: str
    replayed: bool


__all__ = ["ButianConflictError", "ButianError", "ButianResult"]
