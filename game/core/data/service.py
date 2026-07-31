"""所有游戏微服务共享的正式 JSON 数据入口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, RLock
from typing import Any

from .files import JsonDataError, JsonDataReader
from .loading import GameDataLoader, LoadedGameData


@dataclass(frozen=True)
class JsonDataStatus:
    """不暴露内部可变对象的数据微服务状态。"""

    root: Path
    loaded: bool
    document_count: int
    issue_count: int


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
                issue_count=len(loaded.issues) if loaded is not None else 0,
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

    def read(self, relative_path: str | Path) -> Any:
        """按 data 内相对路径返回文档副本。"""

        with self._state_lock:
            loaded = self._require_loaded()
            return deepcopy(loaded.catalog.read(relative_path))

    def scope(self, name: str) -> dict[str, Any]:
        """返回定义、规则、内容或展示作用域的完整副本。"""

        scope_name = str(name or "").strip()
        with self._state_lock:
            loaded = self._require_loaded()
            scopes: Mapping[str, Mapping[str, Any]] = {
                "定义": loaded.definitions,
                "规则": loaded.rules,
                "内容": loaded.content,
                "展示": loaded.presentation,
            }
            values = scopes.get(scope_name)
            if values is None:
                raise JsonDataError(f"未知数据作用域：{scope_name or '<空>'}")
            return deepcopy(dict(values))

    def entity(self, section: str, identity: str) -> dict[str, Any]:
        """按类别和稳定编号取得一个正式实体副本。"""

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
        """取得一个类别的编号去重实体索引副本。"""

        section_name = str(section or "").strip()
        with self._state_lock:
            loaded = self._require_loaded()
            values = loaded.entities.get(section_name)
            if values is None:
                raise JsonDataError(f"未知实体类别：{section_name or '<空>'}")
            return deepcopy({identity: dict(value) for identity, value in values.items()})

    def group(self, file_id: str, section: str) -> tuple[str, ...]:
        """取得一份内容文件在指定类别下声明的实体编号。"""

        group_id = str(file_id or "").strip().removesuffix(".json")
        section_name = str(section or "").strip()
        with self._state_lock:
            loaded = self._require_loaded()
            sections = loaded.groups.get(group_id)
            if sections is None or section_name not in sections:
                raise JsonDataError(f"内容分组不存在：{group_id or '<空>'} -> {section_name or '<空>'}")
            return tuple(sections[section_name])

    def expand_pool(
        self,
        file_ids: Sequence[str],
        section: str,
        *,
        deduplicate: bool = True,
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        """展开资源池，并隔离调用方对实体正文的修改。"""

        with self._state_lock:
            loaded = self._require_loaded()
            values = loaded.expand_pool(tuple(file_ids), section, deduplicate=deduplicate)
            return tuple((identity, deepcopy(value)) for identity, value in values)

    def issues(self) -> tuple[str, ...]:
        with self._state_lock:
            return tuple(self._require_loaded().issues)

    def document_paths(self) -> tuple[str, ...]:
        with self._state_lock:
            return tuple(
                document.relative_path for document in self._require_loaded().catalog.documents
            )

    def _require_loaded(self) -> LoadedGameData:
        if self._loaded is None:
            raise RuntimeError("JSON 数据微服务尚未加载")
        return self._loaded


__all__ = ["JsonDataService", "JsonDataStatus"]
