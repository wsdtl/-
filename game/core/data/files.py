"""运行期按文件名读取 data 目录中的 JSON。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any


class JsonDataError(ValueError):
    """请求的数据文件不存在、越界或不是合法 JSON。"""


DATA_SCOPES = ("定义", "规则", "内容", "展示")
POOL_SECTIONS = frozenset({"道侣", "敌人", "物品", "功法", "附魔", "宝石", "机制"})


@dataclass(frozen=True)
class JsonDocument:
    """一份已经严格解析、但尚未进入玩法执行的 JSON 文档。"""

    relative_path: str
    scope: str
    file_id: str
    value: Any


@dataclass(frozen=True)
class JsonDataCatalog:
    """按定义、规则、内容、展示分阶段注册后的只读数据目录。"""

    documents: tuple[JsonDocument, ...]
    by_path: MappingProxyType
    content_by_file: MappingProxyType

    def read(self, relative_path: str | Path) -> Any:
        key = _path_key(relative_path)
        document = self.by_path.get(key)
        if document is None:
            raise JsonDataError(f"数据文件没有注册：{relative_path}")
        return document.value

    def content_file(self, file_id: str) -> JsonDocument:
        key = str(file_id or "").strip().removesuffix(".json").casefold()
        if not key:
            raise JsonDataError("资源池文件名不能为空")
        document = self.content_by_file.get(key)
        if document is None:
            raise JsonDataError(f"资源池文件不存在：{file_id}.json")
        return document

    def expand_pool(
        self,
        file_ids: list[str] | tuple[str, ...],
        section: str,
        *,
        deduplicate: bool,
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        """按文件顺序展开对象池，可选择保留重复项或按实体身份去重。"""

        section_name = str(section or "").strip()
        if section_name not in POOL_SECTIONS:
            raise JsonDataError(f"不支持的资源池集合：{section_name or '<空>'}")
        result: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for file_id in file_ids:
            document = self.content_file(str(file_id))
            for identity, value in _pool_entries(document, section_name):
                if deduplicate and identity in seen:
                    continue
                seen.add(identity)
                result.append((identity, value))
        if not result:
            joined = "、".join(str(value) for value in file_ids) or "<空>"
            raise JsonDataError(f"资源池为空：{joined} -> {section_name}")
        return tuple(result)


class JsonDataReader:
    """启动时一次性严格解析全部正式 JSON。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def load_catalog(self) -> JsonDataCatalog:
        """一次解析正式数据目录，并建立路径注册表和内容文件名注册表。"""

        documents: list[JsonDocument] = []
        by_path: dict[str, JsonDocument] = {}
        content_by_file: dict[str, JsonDocument] = {}
        content_sources: dict[str, str] = {}
        for scope in DATA_SCOPES:
            directory = self.root / scope
            if not directory.is_dir():
                raise JsonDataError(f"数据目录不存在：{scope}")
            files = sorted(
                directory.rglob("*.json"),
                key=lambda value: value.relative_to(self.root).as_posix().casefold(),
            )
            for path in files:
                relative_path = path.relative_to(self.root).as_posix()
                document = JsonDocument(
                    relative_path=relative_path,
                    scope=scope,
                    file_id=path.stem,
                    value=self._read_path(path, relative_path),
                )
                key = relative_path.casefold()
                if key in by_path:
                    raise JsonDataError(f"数据文件路径重复：{relative_path}")
                by_path[key] = document
                documents.append(document)
                if scope == "内容":
                    file_key = path.stem.casefold()
                    previous = content_sources.get(file_key)
                    if previous is not None:
                        raise JsonDataError(
                            f"内容文件名重复 {path.name}：{previous} 与 {relative_path}"
                        )
                    content_sources[file_key] = relative_path
                    content_by_file[file_key] = document
        return JsonDataCatalog(
            documents=tuple(documents),
            by_path=MappingProxyType(by_path),
            content_by_file=MappingProxyType(content_by_file),
        )

    @staticmethod
    def _read_path(path: Path, display_path: str) -> Any:
        try:
            text = path.read_text(encoding="utf-8")
            return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except (OSError, json.JSONDecodeError, JsonDataError) as exc:
            raise JsonDataError(f"数据文件读取失败：{display_path}：{exc}") from exc

def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonDataError(f"JSON 对象存在重复键：{key}")
        result[key] = value
    return result


def _path_key(relative_path: str | Path) -> str:
    value = Path(str(relative_path or "").strip())
    if value.suffix.lower() != ".json":
        value = value.with_suffix(".json")
    return value.as_posix().casefold()


def _pool_entries(
    document: JsonDocument,
    section: str,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    actual_section = content_section(document)
    if actual_section != section:
        raise JsonDataError(
            f"资源池集合不匹配：{document.relative_path} 是 "
            f"{actual_section or '未知内容'}，不是 {section}"
        )
    root = document.value
    result: list[tuple[str, dict[str, Any]]] = []
    if isinstance(root, list):
        for index, raw in enumerate(root):
            if not isinstance(raw, dict):
                raise JsonDataError(
                    f"资源池对象必须是字典：{document.relative_path} -> {section}[{index}]"
                )
            identity = str(raw.get("编号") or "").strip()
            if not identity:
                raise JsonDataError(
                    f"资源池对象缺少编号：{document.relative_path} -> {section}[{index}]"
                )
            result.append((identity, raw))
    elif isinstance(root, dict):
        for raw_key, raw in root.items():
            if not isinstance(raw, dict):
                raise JsonDataError(
                    f"资源池对象必须是字典：{document.relative_path} -> {section}.{raw_key}"
                )
            result.append((str(raw_key), raw))
    else:
        raise JsonDataError(
            f"资源池根值必须是数组或对象：{document.relative_path} -> {section}"
        )
    return tuple(result)


def content_section(document: JsonDocument) -> str | None:
    """内容文件的稳定名称就是类别声明，JSON 根值不重复包装类别。"""

    if document.scope != "内容":
        return None
    file_id = document.file_id
    parts = PurePosixPath(document.relative_path).parts
    if file_id == "地图规则":
        return "世界"
    if file_id.endswith("道侣"):
        return "道侣"
    if file_id.endswith("敌人"):
        return "敌人"
    if file_id.startswith("功法-"):
        return "功法"
    if file_id.startswith("物品-附魔-"):
        return "附魔"
    if file_id.startswith("物品-宝石-"):
        return "宝石"
    if file_id.startswith("物品-"):
        return "物品"
    if "战斗机制" in parts:
        return "机制"
    if len(parts) >= 4 and parts[1] == "世界" and file_id == parts[-2]:
        return "区域" if len(parts) == 4 else "地点"
    return None


__all__ = [
    "DATA_SCOPES",
    "JsonDataCatalog",
    "JsonDataError",
    "JsonDataReader",
    "JsonDocument",
    "POOL_SECTIONS",
    "content_section",
]
