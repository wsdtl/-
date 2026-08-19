"""铜雀台玩法的稳定请求与结果。"""

from __future__ import annotations

from dataclasses import dataclass


class TongquetaiError(ValueError):
    """当前位置、同行关系或资源不能完成夺元。"""


class TongquetaiConflictError(RuntimeError):
    """夺元提交前相关状态已经变化。"""


@dataclass(frozen=True)
class TongquetaiOutcome:
    mode: str
    offered: int
    accepted: int
    discarded: int


@dataclass(frozen=True)
class TongquetaiPreview:
    location_name: str
    character_name: str
    companion_id: str
    companion_name: str
    companion_level: int
    cultivation: int
    protected: TongquetaiOutcome
    severed: TongquetaiOutcome
    medicine_id: str
    medicine_name: str
    has_medicine: bool


@dataclass(frozen=True)
class TongquetaiRequest:
    user_id: str
    request_id: str
    mode: str


@dataclass(frozen=True)
class TongquetaiSettlement:
    location_name: str
    character_name: str
    companion_id: str
    companion_name: str
    companion_origin: str
    mode: str
    offered: int
    accepted: int
    discarded: int
    affection_before: float
    medicine_id: str
    medicine_name: str
    medicine_grade_name: str
    replayed: bool


__all__ = [
    "TongquetaiConflictError",
    "TongquetaiError",
    "TongquetaiOutcome",
    "TongquetaiPreview",
    "TongquetaiRequest",
    "TongquetaiSettlement",
]
