"""修为转移核心的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class CultivationTransferError(ValueError):
    """正式规则或转移参数无法形成合法结果。"""


@dataclass(frozen=True)
class CultivationTransferStatus:
    initialized: bool
    location_function: str
    medicine_id: str
    minimum_level: int
    guard_rule: str


@dataclass(frozen=True)
class CultivationTransferValues:
    cultivation: int
    protected_amount: int
    severed_amount: int


__all__ = [
    "CultivationTransferError",
    "CultivationTransferStatus",
    "CultivationTransferValues",
]
