"""当前集体行动归属的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass


class ActionGroupError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ActionGroup:
    mode: str
    leader_user_id: str
    participant_user_ids: tuple[str, ...]
    group_id: str = ""


@dataclass(frozen=True)
class ActionGroupServiceStatus:
    initialized: bool


__all__ = ["ActionGroup", "ActionGroupError", "ActionGroupServiceStatus"]
