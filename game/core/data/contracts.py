"""JSON 数据微服务的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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


__all__ = ["JsonDataError", "JsonDataStatus"]
