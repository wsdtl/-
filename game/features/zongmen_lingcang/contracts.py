"""宗门灵藏玩法的稳定结果。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.sect_assets import SectAssetEntry, SectAssetTransfer


class LingcangFeatureError(RuntimeError):
    """当前玩家无法完成灵藏操作。"""


@dataclass(frozen=True)
class LingcangAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class LingcangPage:
    spirit_stones: int
    category: str
    page: int
    page_count: int
    total_entries: int
    entries: tuple[SectAssetEntry, ...]


@dataclass(frozen=True)
class LingcangCopy:
    text: Mapping[str, str]


__all__ = [
    "LingcangAction",
    "LingcangCopy",
    "LingcangFeatureError",
    "LingcangPage",
    "SectAssetTransfer",
]
