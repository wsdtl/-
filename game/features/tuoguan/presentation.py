"""读取托管展示 JSON。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService

from .contracts import HostingCopy


def load_presentation(data: JsonDataService) -> HostingCopy:
    raw = data.dataset("托管展示").get("文本")
    if not isinstance(raw, Mapping):
        raise JsonDataError("托管展示缺少文本.json")
    text = MappingProxyType(
        {
            str(section): MappingProxyType(
                {str(key): str(value) for key, value in _mapping(value, str(section)).items()}
            )
            for section, value in raw.items()
        }
    )
    if set(text) != {"图标", "结果", "错误"}:
        raise JsonDataError("托管文本必须完整包含图标、结果、错误")
    return HostingCopy(text)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


__all__ = ["load_presentation"]
