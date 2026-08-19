"""读取山门展示 JSON。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService

from .contracts import GateAction, GateCopy


def load_presentation(data: JsonDataService) -> tuple[GateCopy, tuple[Mapping[str, str], ...]]:
    dataset = data.dataset("山门展示")
    raw_text = dataset.get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("山门展示缺少文本.json")
    text = MappingProxyType(
        {
            str(section): MappingProxyType(
                {str(key): str(value) for key, value in _mapping(raw, str(section)).items()}
            )
            for section, raw in raw_text.items()
        }
    )
    if set(text) != {"图标", "结果", "错误"}:
        raise JsonDataError("山门文本必须完整包含图标、结果、错误")
    raw_buttons = data.dataset("山门按钮").get("按钮")
    if not isinstance(raw_buttons, Sequence) or isinstance(raw_buttons, (str, bytes)):
        raise JsonDataError("山门按钮必须是字典列表")
    buttons = tuple(
        MappingProxyType(
            {key: str(_mapping(raw, "山门按钮[]").get(key) or "").strip() for key in ("位置", "编号", "名称", "命令", "行为", "样式")}
        )
        for raw in raw_buttons
    )
    if len({button["编号"] for button in buttons}) != len(buttons):
        raise JsonDataError("山门按钮编号不能重复")
    if any(button["位置"] not in {"山门入口", "宗门洞天"} for button in buttons):
        raise JsonDataError("山门按钮位置无效")
    return GateCopy(text), buttons


def actions(buttons: tuple[Mapping[str, str], ...], position: str) -> tuple[GateAction, ...]:
    return tuple(
        GateAction(
            button["编号"],
            button["名称"],
            button["命令"],
            button["行为"],
            button["样式"],
        )
        for button in buttons
        if button["位置"] == position
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


__all__ = ["actions", "load_presentation"]
