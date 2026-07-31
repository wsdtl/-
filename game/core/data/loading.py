"""正式 JSON 的分阶段注册、分组和编号实体索引。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .files import (
    JsonDataCatalog,
    JsonDataError,
    JsonDataReader,
    JsonDocument,
    content_section,
)


COLLECTION_SECTIONS = (
    "世界",
    "区域",
    "地点",
    "敌人",
    "道侣",
    "物品",
    "功法",
    "附魔",
    "宝石",
    "机制",
)
NUMBERED_SECTIONS = frozenset({"道侣", "物品", "功法", "附魔", "宝石", "机制"})

@dataclass(frozen=True)
class LoadedGameData:
    catalog: JsonDataCatalog
    definitions: Mapping[str, Any]
    rules: Mapping[str, Any]
    content: Mapping[str, Any]
    presentation: Mapping[str, Any]
    groups: Mapping[str, Mapping[str, tuple[str, ...]]]
    entities: Mapping[str, Mapping[str, Any]]
    issues: tuple[str, ...]

    def expand_pool(
        self,
        file_ids: list[str] | tuple[str, ...],
        section: str,
        *,
        deduplicate: bool,
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        return self.catalog.expand_pool(file_ids, section, deduplicate=deduplicate)


class GameDataLoader:
    """注册四类正式 JSON，并建立分组与编号实体索引。"""

    def __init__(self, reader: JsonDataReader) -> None:
        self.reader = reader

    def load(self) -> LoadedGameData:
        catalog = self.reader.load_catalog()
        scopes = {
            scope: _scope_values(catalog.documents, scope)
            for scope in ("定义", "规则", "内容", "展示")
        }
        groups, entities, issues = _index_content(catalog)
        return LoadedGameData(
            catalog=catalog,
            definitions=MappingProxyType(scopes["定义"]),
            rules=MappingProxyType(scopes["规则"]),
            content=MappingProxyType(scopes["内容"]),
            presentation=MappingProxyType(scopes["展示"]),
            groups=MappingProxyType(
                {file_id: MappingProxyType(sections) for file_id, sections in groups.items()}
            ),
            entities=MappingProxyType(
                {section: MappingProxyType(values) for section, values in entities.items()}
            ),
            issues=tuple(dict.fromkeys(issues)),
        )


def _scope_values(documents: tuple[JsonDocument, ...], scope: str) -> dict[str, Any]:
    return {
        document.relative_path: document.value
        for document in documents
        if document.scope == scope
    }


def _index_content(
    catalog: JsonDataCatalog,
) -> tuple[
    dict[str, dict[str, tuple[str, ...]]],
    dict[str, dict[str, Mapping[str, Any]]],
    list[str],
]:
    groups: dict[str, dict[str, tuple[str, ...]]] = {}
    entities: dict[str, dict[str, Mapping[str, Any]]] = {
        section: {} for section in NUMBERED_SECTIONS
    }
    sources: dict[str, dict[str, str]] = {section: {} for section in NUMBERED_SECTIONS}
    conflict_sources: dict[str, dict[str, set[str]]] = {
        section: {} for section in NUMBERED_SECTIONS
    }
    for document in catalog.documents:
        if document.scope != "内容":
            continue
        sections = _document_collections(document)
        groups[document.file_id] = {}
        for section, entries in sections.items():
            groups[document.file_id][section] = tuple(identity for identity, _ in entries)
            if section not in NUMBERED_SECTIONS:
                continue
            for identity, value in entries:
                previous = entities[section].get(identity)
                if previous is None:
                    entities[section][identity] = value
                    sources[section][identity] = document.relative_path
                elif _entity_identity(previous) != _entity_identity(value):
                    conflict_sources[section].setdefault(
                        identity,
                        {sources[section][identity]},
                    ).add(document.relative_path)
    issues = []
    for section, conflicts in conflict_sources.items():
        for identity, paths in conflicts.items():
            ordered = sorted(paths, key=str.casefold)
            issues.append(
                f"实体编号 {identity} 被 {len(ordered)} 份文件用于不同{section}："
                f"{ordered[0]} 等"
            )
    return groups, entities, issues


def _entity_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    """所有编号实体都以实际定义判同，池内上下文不属于实体。"""

    return {str(key): raw for key, raw in value.items()}


def _document_collections(
    document: JsonDocument,
) -> dict[str, tuple[tuple[str, Mapping[str, Any]], ...]]:
    value = document.value
    section = content_section(document)
    if section not in COLLECTION_SECTIONS:
        return {}
    if section in NUMBERED_SECTIONS:
        if not isinstance(value, list):
            raise JsonDataError(
                f"编号内容文件根值必须是数组：{document.relative_path} -> {section}"
            )
        return {section: _array_entries(value, document, section)}
    if not isinstance(value, dict):
        raise JsonDataError(
            f"命名内容文件根值必须是对象：{document.relative_path} -> {section}"
        )
    if section in {"世界", "区域", "地点"}:
        identity = str(value.get("名称") or document.file_id)
        return {section: ((identity, value),)}
    return {
        section: tuple(
            (str(key), raw)
            for key, raw in value.items()
            if isinstance(raw, dict)
        )
    }


def _array_entries(
    values: list[Any],
    document: JsonDocument,
    section: str,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    result = []
    for index, raw in enumerate(values):
        if not isinstance(raw, dict):
            raise JsonDataError(
                f"内容对象必须是字典：{document.relative_path} -> {section}[{index}]"
            )
        identity = str(raw.get("编号") or "").strip()
        if not identity:
            raise JsonDataError(
                f"内容对象缺少编号：{document.relative_path} -> {section}[{index}]"
            )
        result.append((identity, raw))
    return tuple(result)


__all__ = [
    "GameDataLoader",
    "LoadedGameData",
]
