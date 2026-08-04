"""JSON 数据微服务的稳定公共契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


class JsonDataError(ValueError):
    """正式数据不存在、越界或不符合 JSON 数据契约。"""


@dataclass(frozen=True)
class JsonDataStatus:
    root: Path
    loaded: bool
    document_count: int
    content_document_count: int
    entity_count: int
    pool_count: int


@dataclass(frozen=True)
class JsonEntity:
    """数据服务交付的稳定实体身份、来源和不可变正文。"""

    identity: str
    section: str
    number_category: str
    source_file: str
    directory_owner: str
    value: Mapping[str, JsonValue]


__all__ = ["JsonDataError", "JsonDataStatus", "JsonEntity", "JsonValue"]
