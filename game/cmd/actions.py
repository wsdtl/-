"""把玩法动作契约转换为公共消息动作。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from message import Action


class CommandAction(Protocol):
    """命令回复可消费的最小动作契约。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str


def message_actions(values: Iterable[CommandAction]) -> tuple[Action, ...]:
    """保持玩法给出的顺序，把动作转换为协议中立按钮。"""

    return tuple(
        Action(
            value.action_id,
            value.label,
            value.command,
            behavior=value.behavior,
            style=value.style,
        )
        for value in values
    )


__all__ = ["CommandAction", "message_actions"]
