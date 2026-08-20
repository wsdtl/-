"""读取宗门展示 JSON。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService

from .contracts import SectAction, SectCopy


def load_presentation(
    data: JsonDataService,
) -> tuple[SectCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("宗门展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("宗门展示缺少文本.json")
    text = MappingProxyType(
        {
            str(section): MappingProxyType(
                {
                    str(key): str(value)
                    for key, value in _mapping(raw, str(section)).items()
                }
            )
            for section, raw in raw_text.items()
        }
    )
    if set(text) != {"图标", "格式", "查看", "结果", "错误"}:
        raise JsonDataError("宗门文本必须完整包含图标、格式、查看、结果、错误")
    raw_buttons = data.dataset("宗门按钮").get("按钮")
    if not isinstance(raw_buttons, Sequence) or isinstance(raw_buttons, (str, bytes)):
        raise JsonDataError("宗门按钮必须是字典列表")
    buttons = tuple(
        MappingProxyType(
            {
                key: str(_mapping(raw, "宗门按钮[]").get(key) or "").strip()
                for key in ("页面", "编号", "名称", "命令", "行为", "样式")
            }
        )
        for raw in raw_buttons
    )
    if len({button["编号"] for button in buttons}) != len(buttons):
        raise JsonDataError("宗门按钮编号不能重复")
    if any(
        button["页面"] not in {"未加入", "待处理邀请", "宗主", "长老", "弟子"}
        for button in buttons
    ):
        raise JsonDataError("宗门按钮使用了未知页面")
    return SectCopy(text), buttons


def actions(
    buttons: tuple[Mapping[str, str], ...], page: str
) -> tuple[SectAction, ...]:
    return tuple(
        SectAction(
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
