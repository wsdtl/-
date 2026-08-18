"""布阵玩法微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.formation import FormationArmResult


class FormationArmFeatureError(RuntimeError):
    """布阵玩法无法完成请求。"""


@dataclass(frozen=True)
class FormationArmCopy:
    text: Mapping[str, Mapping[str, str]]


__all__ = ["FormationArmCopy", "FormationArmFeatureError", "FormationArmResult"]
