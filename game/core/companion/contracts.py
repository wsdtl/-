"""世界道侣核心微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompanionStatus:
    initialized: bool
    companion_count: int
    location_count: int


@dataclass(frozen=True)
class LocalCultivator:
    companion_id: str
    name: str
    gender: str
    title: str
    description: str
    realm_id: str
    realm_name: str
    level: int
    interactable: bool


__all__ = ["CompanionStatus", "LocalCultivator"]
