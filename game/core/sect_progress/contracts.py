"""宗门贡献与等级的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class SectProgressError(RuntimeError):
    """宗门贡献或等级无法读取。"""


@dataclass(frozen=True)
class SectProgressSnapshot:
    sect_id: str
    level: int
    maximum_level: int
    total_contribution: int
    next_level_contribution: int | None
    production_multiplier: float
    gathering_multiplier: float
    facility_cost_multiplier: float


@dataclass(frozen=True)
class SectProgressStatus:
    initialized: bool
    maximum_level: int


__all__ = ["SectProgressError", "SectProgressSnapshot", "SectProgressStatus"]
