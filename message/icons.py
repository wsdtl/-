"""公共消息图标注册表。

消息协议只提供中立分类。具体游戏通过 ``register_icons`` 注册自己的图标，
公共消息层不反向导入任何游戏包。
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from types import MappingProxyType


_ICON_KEY = re.compile(r"^[a-z][a-z0-9_.-]*$")
_BASE_SOURCE = "message.base"
_icon_values: dict[str, str] = {
    "guide": "📜",
    "help": "📜",
    "docs": "📜",
    "history": "📜",
    "news": "📰",
    "log": "📄",
    "status": "🌱",
    "player": "🌱",
    "profile": "🌱",
    "mood": "🎐",
    "notice": "📌",
    "system": "✨",
    "map": "🗺️",
    "navigation": "🧭",
    "trade": "💰",
    "inventory": "📦",
    "item": "📦",
    "material": "🧱",
    "reward": "🎁",
    "combat": "⚔️",
    "explore": "🥾",
    "recovery": "🌿",
    "weapon": "⚔️",
    "equipment": "🛡️",
    "skill": "📘",
    "world": "🌏",
    "admin": "🧩",
    "message": "💬",
    "config": "⚙️",
    "test": "📏",
}
_icon_sources: dict[str, str] = {key: _BASE_SOURCE for key in _icon_values}
SECTION_ICONS: Mapping[str, str] = MappingProxyType(_icon_values)


def register_icons(source: object, icons: Mapping[object, object]) -> None:
    """为一个内容来源注册图标；重复注册必须完全一致。"""

    source_name = str(source or "").strip()
    if not source_name:
        raise ValueError("消息图标来源不能为空")
    if not isinstance(icons, Mapping):
        raise TypeError("消息图标必须使用 mapping 注册")

    normalized: dict[str, str] = {}
    for raw_key, raw_icon in icons.items():
        key = str(raw_key or "").strip()
        icon = str(raw_icon or "").strip()
        if not _ICON_KEY.fullmatch(key):
            raise ValueError(f"消息图标 key 不合法：{key or '<empty>'}")
        if not icon or any(character in icon for character in ("\r", "\n", "\t")):
            raise ValueError(f"消息图标内容不合法：{key}")
        if len(icon) > 16:
            raise ValueError(f"消息图标内容过长：{key}")
        normalized[key] = icon

    for key, icon in normalized.items():
        existing = _icon_values.get(key)
        if existing is None:
            continue
        if existing != icon or _icon_sources[key] != source_name:
            raise ValueError(f"消息图标分类已由 {_icon_sources[key]} 注册：{key}")

    for key, icon in normalized.items():
        _icon_values[key] = icon
        _icon_sources[key] = source_name


def icon_for(key: object) -> str:
    """按分类 key 返回图标；未知 key 立即暴露配置错误。"""

    value = str(key or "").strip()
    if not value:
        return ""
    try:
        return SECTION_ICONS[value]
    except KeyError as exc:
        raise ValueError(f"未知消息图标分类：{value}") from exc
