"""读取采药展示 JSON 并生成强业务联动动作。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService

from .contracts import HerbGatheringAction, HerbGatheringCopy


def load_presentation(
    data: JsonDataService,
) -> tuple[HerbGatheringCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("采药展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("采药展示缺少文本.json")
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
    rows = data.dataset("采药按钮").get("按钮")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise JsonDataError("采药按钮必须是字典列表")
    buttons = tuple(
        MappingProxyType(
            {
                key: str(_mapping(raw, "采药按钮[]").get(key) or "").strip()
                for key in ("页面", "条件", "编号", "名称", "命令", "行为", "样式")
            }
        )
        for raw in rows
    )
    _validate_buttons(buttons, "采药")
    return HerbGatheringCopy(text), buttons


def actions(
    buttons: tuple[Mapping[str, str], ...],
    page: str,
    conditions: set[str],
    variables: Mapping[str, object] | None = None,
) -> tuple[HerbGatheringAction, ...]:
    values = {str(key): str(value) for key, value in (variables or {}).items()}
    return tuple(
        HerbGatheringAction(
            button["编号"],
            button["名称"],
            button["命令"].format_map(values),
            button["行为"],
            button["样式"],
        )
        for button in buttons
        if button["页面"] == page
        and (not button["条件"] or button["条件"] in conditions)
    )


def _validate_buttons(buttons: tuple[Mapping[str, str], ...], label: str) -> None:
    if any(button["页面"] not in {"开始", "进度", "总结"} for button in buttons):
        raise JsonDataError(f"{label}按钮使用了未知页面")
    identities = tuple((button["页面"], button["编号"]) for button in buttons)
    if len(identities) != len(set(identities)):
        raise JsonDataError(f"{label}同一页面的按钮编号不能重复")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


__all__ = ["actions", "load_presentation"]
