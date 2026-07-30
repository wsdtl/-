"""现行 JSON 数据的分阶段注册、引用解析与启动前审查。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from game.core import (
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
    "词条",
    "机制",
    "战斗方向",
)
NUMBERED_SECTIONS = frozenset({"道侣", "物品", "功法", "附魔", "宝石"})
POOL_FIELDS = {
    "功法池": "功法",
    "附魔池": "附魔",
    "宝石池": "宝石",
    "道侣池": "道侣",
    "敌人池": "敌人",
    "天材地宝池": "物品",
    "喜爱天材地宝池": "物品",
    "物品池": "物品",
}


class GameDataLoadError(ValueError):
    """数据可以解析，但尚未满足进入玩法执行的条件。"""


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

    def require_valid(self) -> None:
        if not self.issues:
            return
        shown = self.issues[:20]
        suffix = "" if len(self.issues) <= len(shown) else f"\n...另有 {len(self.issues) - len(shown)} 项"
        raise GameDataLoadError("JSON 数据未通过启动校验：\n- " + "\n- ".join(shown) + suffix)

    def expand_pool(
        self,
        file_ids: list[str] | tuple[str, ...],
        section: str,
        *,
        deduplicate: bool,
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        return self.catalog.expand_pool(file_ids, section, deduplicate=deduplicate)


class GameDataLoader:
    """严格执行定义、规则、内容、引用校验、展示五个加载阶段。"""

    def __init__(self, reader: JsonDataReader) -> None:
        self.reader = reader

    def load(self) -> LoadedGameData:
        catalog = self.reader.load_catalog()
        scopes = {
            scope: _scope_values(catalog.documents, scope)
            for scope in ("定义", "规则", "内容", "展示")
        }
        groups, entities, issues = _index_content(catalog)
        issues.extend(_validate_score_boundaries(catalog))
        issues.extend(_validate_pool_references(catalog))
        issues.extend(_validate_world(catalog))
        issues.extend(_validate_numbering(catalog, entities))
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


def load_game_data(root: str | Path, *, require_valid: bool = True) -> LoadedGameData:
    loaded = GameDataLoader(JsonDataReader(root)).load()
    if require_valid:
        loaded.require_valid()
    return loaded


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

    return {
        str(key): raw
        for key, raw in value.items()
        if key not in {"说明", "权重", "评分"}
    }


def _validate_score_boundaries(catalog: JsonDataCatalog) -> list[str]:
    issues: list[str] = []
    for document in catalog.documents:
        for field, _ in _walk_fields(document.value):
            if field in {"评分", "评分模型"}:
                issues.append(
                    f"{document.relative_path} -> {field} 只能存在于 tools/战斗校验"
                )
    return issues


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


def _validate_pool_references(catalog: JsonDataCatalog) -> list[str]:
    issues: list[str] = []
    for document in catalog.documents:
        if document.scope != "内容":
            continue
        for field, values in _walk_fields(document.value):
            section = POOL_FIELDS.get(field)
            if section is None or not isinstance(values, list):
                continue
            for file_id in values:
                if not isinstance(file_id, str) or not file_id.strip():
                    issues.append(f"{document.relative_path} -> {field} 必须使用非空文件名")
                    continue
                try:
                    catalog.expand_pool((file_id,), section, deduplicate=False)
                except JsonDataError as exc:
                    issues.append(f"{document.relative_path} -> {field}: {exc}")
    return issues


def _walk_fields(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _walk_fields(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_fields(child)


def _validate_world(catalog: JsonDataCatalog) -> list[str]:
    issues: list[str] = []
    try:
        world = catalog.content_file("地图规则").value
        bounds = _axis_bounds(world["坐标边界"], "地图规则.坐标边界")
    except (JsonDataError, KeyError, TypeError, ValueError) as exc:
        return [f"世界规则无法读取：{exc}"]
    if bounds[2] != (0, 0):
        issues.append("当前世界 z轴边界必须固定为 [0, 0]")

    regions: dict[str, tuple[tuple[int, int], tuple[int, int], tuple[int, int]]] = {}
    locations: list[tuple[str, Mapping[str, Any], str]] = []
    for document in catalog.documents:
        if document.scope != "内容":
            continue
        sections = _document_collections(document)
        for region_id, definition in sections.get("区域", ()):
            try:
                region_bounds = _axis_bounds(
                    definition["坐标范围"],
                    f"{document.relative_path} -> 区域.{region_id}.坐标范围",
                )
                if not _bounds_within(region_bounds, bounds):
                    issues.append(f"区域 {region_id} 的坐标范围超出世界边界")
                if region_bounds[2] != (0, 0):
                    issues.append(f"区域 {region_id} 的 z轴边界当前必须固定为 [0, 0]")
                regions[str(region_id)] = region_bounds
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(str(exc))
        for location_id, definition in sections.get("地点", ()):
            locations.append((str(location_id), definition, document.relative_path))

    seen: dict[tuple[int, int, int], str] = {}
    for location_id, definition, source in locations:
        try:
            coordinate = _coordinate(definition["坐标"], f"{source} -> 地点.{location_id}.坐标")
            region_id = str(definition["所属区域"])
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(str(exc))
            continue
        if coordinate[2] != 0:
            issues.append(f"地点 {location_id} 当前必须位于 z=0")
        if not _coordinate_within(coordinate, bounds):
            issues.append(f"地点 {location_id} 的坐标超出世界边界")
        region_bounds = regions.get(region_id)
        if region_bounds is None:
            issues.append(f"地点 {location_id} 引用了未知区域 {region_id}")
        elif not _coordinate_within(coordinate, region_bounds):
            issues.append(f"地点 {location_id} 的坐标超出所属区域 {region_id}")
        previous = seen.get(coordinate)
        if previous is not None:
            issues.append(f"地点 {location_id} 与 {previous} 使用了相同三轴坐标 {coordinate}")
        else:
            seen[coordinate] = location_id
    starting_location = str(world.get("出生地") or "")
    if starting_location not in {location_id for location_id, _, _ in locations}:
        issues.append(f"世界出生地引用了未知地点 {starting_location or '<空>'}")
    return issues


def _validate_numbering(
    catalog: JsonDataCatalog,
    entities: dict[str, dict[str, Mapping[str, Any]]],
) -> list[str]:
    issues: list[str] = []
    try:
        definition = catalog.read("定义/编号.json")
        prefixes = {
            str(value["类别"]): str(value["前缀"])
            for value in definition["编号前缀"]
        }
        digits = int(definition["编号规则"]["位数"])
    except (JsonDataError, KeyError, TypeError, ValueError) as exc:
        return [f"编号定义无法读取：{exc}"]
    section_categories = {"道侣": "道侣", "功法": "功法", "附魔": "附魔技能书", "宝石": "宝石"}
    for section, values in entities.items():
        for identity, value in values.items():
            if len(identity) != digits or not identity.isdigit():
                issues.append(f"{section}编号 {identity} 必须是 {digits} 位数字字符串")
                continue
            category = str(value.get("类别") or section_categories.get(section) or "")
            expected = prefixes.get(category)
            if expected is None:
                issues.append(f"{section}编号 {identity} 使用了未登记类别 {category or '<空>'}")
            elif not identity.startswith(expected):
                issues.append(f"{section}编号 {identity} 与类别 {category} 的前缀 {expected} 不一致")
    return issues


def _axis_bounds(value: Any, path: str):
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是对象")
    return tuple(_range(value.get(axis), f"{path}.{axis}") for axis in ("x轴", "y轴", "z轴"))


def _range(value: Any, path: str) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{path} 必须是 [最小值, 最大值]")
    low, high = value
    if isinstance(low, bool) or isinstance(high, bool) or not isinstance(low, int) or not isinstance(high, int):
        raise ValueError(f"{path} 必须使用整数")
    if high < low:
        raise ValueError(f"{path} 最大值不能小于最小值")
    return low, high


def _coordinate(value: Any, path: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise ValueError(f"{path} 必须是整数 [x, y, z]")
    return value[0], value[1], value[2]


def _bounds_within(inner, outer) -> bool:
    return all(
        outer_axis[0] <= inner_axis[0] <= inner_axis[1] <= outer_axis[1]
        for inner_axis, outer_axis in zip(inner, outer)
    )


def _coordinate_within(coordinate, bounds) -> bool:
    return all(low <= value <= high for value, (low, high) in zip(coordinate, bounds))


__all__ = [
    "GameDataLoadError",
    "GameDataLoader",
    "LoadedGameData",
    "load_game_data",
]
