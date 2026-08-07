"""查看角色玩法的公共结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.character import CharacterProfile


class CharacterOverviewError(RuntimeError):
    """查看角色玩法无法完成。"""


class CharacterOverviewMissingError(CharacterOverviewError):
    """用户尚未创建人物。"""


@dataclass(frozen=True)
class CharacterOverviewResult:
    character: CharacterProfile
    location_name: str
    region: str
    terrain: str
    altitude: int
    states: tuple[tuple[str, str], ...]


__all__ = [
    "CharacterOverviewError",
    "CharacterOverviewMissingError",
    "CharacterOverviewResult",
]
