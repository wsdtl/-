"""炼阵玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.formation import FormationOverview, FormationPreview, FormationResult


class FormationCraftFeatureError(RuntimeError):
    """炼阵玩法无法完成请求。"""


@dataclass(frozen=True)
class FormationAction:
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class FormationCopy:
    text: Mapping[str, Mapping[str, str]]


__all__ = [
    "FormationAction",
    "FormationCopy",
    "FormationCraftFeatureError",
    "FormationOverview",
    "FormationPreview",
    "FormationResult",
]
