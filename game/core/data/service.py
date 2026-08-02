"""所有游戏微服务共享的正式 JSON 数据入口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from threading import Lock, RLock
from typing import Any

from .contracts import JsonDataError, JsonDataStatus
from .files import JsonDataReader
from .loading import GameDataLoader, LoadedGameData


class JsonDataService:
    """启动时加载全部正式 JSON，并在进程内提供只读数据快照。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._state_lock = RLock()
        self._load_lock = Lock()
        self._loaded: LoadedGameData | None = None

    @property
    def root(self) -> Path:
        return self._root

    def status(self) -> JsonDataStatus:
        with self._state_lock:
            loaded = self._loaded
            return JsonDataStatus(
                root=self._root,
                loaded=loaded is not None,
                document_count=len(loaded.catalog.documents) if loaded is not None else 0,
                content_document_count=(
                    sum(
                        document.scope == "内容"
                        for document in loaded.catalog.documents
                    )
                    if loaded is not None
                    else 0
                ),
                entity_count=loaded.entity_count if loaded is not None else 0,
                pool_count=loaded.pool_count if loaded is not None else 0,
            )

    def initialize(self) -> JsonDataStatus:
        """构建本进程唯一快照；数据更新必须通过重启服务生效。"""

        with self._load_lock:
            with self._state_lock:
                if self._loaded is not None:
                    raise RuntimeError("正式 JSON 已加载；数据更新必须重启服务")

            loaded = GameDataLoader(JsonDataReader(self._root)).load()
            with self._state_lock:
                self._loaded = loaded
            return self.status()

    def dataset(self, name: str) -> dict[str, Any]:
        """按读取规则声明的数据名返回一个服务数据集副本。"""

        dataset_name = str(name or "").strip()
        with self._state_lock:
            documents = self._require_loaded().catalog.dataset(dataset_name)
            return {
                document.descriptor.data_name: deepcopy(document.value)
                for document in documents
            }

    def entity(self, section: str, identity: str) -> dict[str, Any]:
        """按类别和稳定身份取得一个正式实体副本。"""

        section_name = str(section or "").strip()
        entity_id = str(identity or "").strip()
        with self._state_lock:
            loaded = self._require_loaded()
            values = loaded.entities.get(section_name)
            if values is None:
                raise JsonDataError(f"未知实体类别：{section_name or '<空>'}")
            value = values.get(entity_id)
            if value is None:
                raise JsonDataError(f"实体不存在：{section_name} {entity_id or '<空>'}")
            return deepcopy(dict(value))

    def entities(self, section: str) -> dict[str, dict[str, Any]]:
        """取得一个类别的身份去重实体索引副本。"""

        section_name = str(section or "").strip()
        with self._state_lock:
            loaded = self._require_loaded()
            values = loaded.entities.get(section_name)
            if values is None:
                raise JsonDataError(f"未知实体类别：{section_name or '<空>'}")
            return deepcopy({identity: dict(value) for identity, value in values.items()})

    def entity_fields(
        self,
        section: str,
        fields: Sequence[str],
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        """取得一个类别的指定实体字段，不复制完整实体正文。"""

        section_name = str(section or "").strip()
        field_names = _field_names(fields)
        with self._state_lock:
            loaded = self._require_loaded()
            values = loaded.entities.get(section_name)
            if values is None:
                raise JsonDataError(f"未知实体类别：{section_name or '<空>'}")
            return tuple(
                (identity, _select_fields(value, field_names))
                for identity, value in values.items()
            )

    def pool_members(
        self,
        file_ids: Sequence[str],
        section: str,
        *,
        deduplicate: bool = True,
    ) -> tuple[str, ...]:
        """展开资源池，只返回稳定身份，不暴露实体正文。"""

        with self._state_lock:
            loaded = self._require_loaded()
            values = loaded.resolve_pool(
                tuple(file_ids),
                section,
                deduplicate=deduplicate,
            )
            return tuple(identity for identity, _ in values)

    def pool_fields(
        self,
        file_ids: Sequence[str],
        section: str,
        fields: Sequence[str],
        *,
        deduplicate: bool = True,
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        """展开资源池，并仅复制调用方明确请求的实体字段。"""

        field_names = _field_names(fields)
        with self._state_lock:
            loaded = self._require_loaded()
            values = loaded.resolve_pool(
                tuple(file_ids),
                section,
                deduplicate=deduplicate,
            )
            return tuple(
                (
                    identity,
                    _select_fields(value, field_names),
                )
                for identity, value in values
            )

    def document_paths(self) -> tuple[str, ...]:
        with self._state_lock:
            return tuple(
                document.relative_path for document in self._require_loaded().catalog.documents
            )

    def _require_loaded(self) -> LoadedGameData:
        if self._loaded is None:
            raise RuntimeError("JSON 数据微服务尚未加载")
        return self._loaded


def _field_names(fields: Sequence[str]) -> tuple[str, ...]:
    field_names = tuple(str(field or "").strip() for field in fields)
    if not field_names or any(not field for field in field_names):
        raise JsonDataError("实体字段不能为空")
    if len(field_names) != len(set(field_names)):
        raise JsonDataError("实体字段不能重复")
    return field_names


def _select_fields(
    value: Mapping[str, Any],
    fields: Sequence[str],
) -> dict[str, Any]:
    return {
        field: deepcopy(value[field])
        for field in fields
        if field in value
    }


__all__ = ["JsonDataService"]
