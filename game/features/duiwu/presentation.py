"""读取队伍展示 JSON。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService

from .contracts import TeamAction, TeamCopy


def load_presentation(
    data: JsonDataService,
) -> tuple[TeamCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("队伍展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("队伍展示缺少文本.json")
    text = MappingProxyType(
        {
            str(section): MappingProxyType(
                {str(key): str(value) for key, value in _mapping(raw, str(section)).items()}
            )
            for section, raw in raw_text.items()
        }
    )
    required_sections = {"图标", "格式", "查看", "结果", "错误"}
    if set(text) != required_sections:
        raise JsonDataError("队伍文本必须完整包含图标、格式、查看、结果、错误")
    raw_buttons = data.dataset("队伍按钮").get("按钮")
    if not isinstance(raw_buttons, Sequence) or isinstance(raw_buttons, (str, bytes)):
        raise JsonDataError("队伍按钮必须是字典列表")
    buttons = tuple(
        MappingProxyType(
            {
                key: str(_mapping(raw, "队伍按钮[]").get(key) or "").strip()
                for key in ("页面", "编号", "名称", "命令", "行为", "样式")
            }
        )
        for raw in raw_buttons
    )
    identities = tuple(button["编号"] for button in buttons)
    if len(identities) != len(set(identities)):
        raise JsonDataError("队伍按钮编号不能重复")
    if any(button["页面"] not in {"未组队", "待处理邀请", "队长", "队员"} for button in buttons):
        raise JsonDataError("队伍按钮使用了未知页面")
    return TeamCopy(text), buttons


def actions(
    buttons: tuple[Mapping[str, str], ...], page: str
) -> tuple[TeamAction, ...]:
    return tuple(
        TeamAction(
            button["编号"],
            button["名称"],
            button["命令"],
            button["行为"],
            button["样式"],
        )
        for button in buttons
        if button["页面"] == page
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


__all__ = ["actions", "load_presentation"]
