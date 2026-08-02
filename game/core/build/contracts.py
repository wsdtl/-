"""构筑生成微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class BuildError(ValueError):
    """候选池或相冲规则无法形成合法构筑。"""


@dataclass(frozen=True)
class BuildStatus:
    initialized: bool
    conflict_count: int
    attempt_limit: int


@dataclass(frozen=True)
class BuildSlotRequest:
    section: str
    count: int
    file_ids: tuple[str, ...] = ()
    full_pool: bool = False


@dataclass(frozen=True)
class BuildRequest:
    slots: tuple[BuildSlotRequest, ...]
    seed: int | None = None


@dataclass(frozen=True)
class BuildSelection:
    section: str
    identities: tuple[str, ...]


@dataclass(frozen=True)
class BuildResult:
    seed: int
    attempts: int
    selections: tuple[BuildSelection, ...]

    @property
    def identities(self) -> tuple[str, ...]:
        return tuple(
            identity
            for selection in self.selections
            for identity in selection.identities
        )


__all__ = [
    "BuildError",
    "BuildRequest",
    "BuildResult",
    "BuildSelection",
    "BuildSlotRequest",
    "BuildStatus",
]
