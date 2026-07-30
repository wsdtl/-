"""地点组件公开的稳定数据。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocationSummary:
    location_id: str
    name: str
    location_type: str
    terrain: str
    functions: tuple[str, ...]
    npcs: tuple[str, ...]
    enemies: tuple[str, ...]
    x: int
    y: int
    z: int

    @property
    def coordinate_text(self) -> str:
        return f"({self.x}, {self.y}, {self.z})"

    @property
    def label(self) -> str:
        return f"{self.name} {self.coordinate_text}"


@dataclass(frozen=True)
class LocationState:
    location_id: str
    name: str
    location_type: str
    terrain: str
    description: str
    functions: tuple[str, ...]
    npcs: tuple[str, ...]
    enemies: tuple[str, ...]
    x: int
    y: int
    z: int

    @property
    def coordinate_text(self) -> str:
        return f"({self.x}, {self.y}, {self.z})"

    @property
    def label(self) -> str:
        return f"{self.name} {self.coordinate_text}"


@dataclass(frozen=True)
class MoveResult:
    status: str
    current: LocationState
    previous: LocationState | None = None
    distance: int = 0


__all__ = ["LocationState", "LocationSummary", "MoveResult"]
