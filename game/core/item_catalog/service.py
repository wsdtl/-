"""面向其他游戏服务的只读物品查询索引。"""

from __future__ import annotations

from collections import defaultdict
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService

from .contracts import (
    ItemCatalogStatus,
    ItemDetail,
    ItemNameAmbiguousError,
    ItemNotFoundError,
    ItemSummary,
)

ITEM_SECTION = "物品"
_PUBLIC_FIELDS = frozenset({"编号", "名称", "说明", "使用效果", "强度"})


class ItemCatalogService:
    """启动时从 JSON 快照建立物品编号索引和名称索引。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._initialized = False
        self._items: dict[str, ItemDetail] = {}
        self._names: dict[str, tuple[ItemSummary, ...]] = {}
        self._categories: dict[str, tuple[ItemSummary, ...]] = {}

    def initialize(self) -> ItemCatalogStatus:
        if self._initialized:
            raise RuntimeError("物品查询微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于物品查询微服务启动")

        by_name: dict[str, list[ItemSummary]] = defaultdict(list)
        by_category: dict[str, list[ItemSummary]] = defaultdict(list)
        for item_id, value in self._data.entities(ITEM_SECTION).items():
            record = self._data.entity_record(ITEM_SECTION, item_id)
            name = _required_text(value.get("名称"), f"物品 {item_id}.名称")
            description = _required_text(value.get("说明"), f"物品 {item_id}.说明")
            category = record.number_category
            if not category:
                raise JsonDataError(f"物品缺少编号类别：{item_id}")
            detail = ItemDetail(
                item_id=item_id,
                category=category,
                name=name,
                description=description,
                fields=MappingProxyType(
                    {
                        str(key): raw
                        for key, raw in value.items()
                        if str(key) in _PUBLIC_FIELDS and str(key) not in {"编号", "名称", "说明"}
                    }
                ),
            )
            self._items[item_id] = detail
            summary = ItemSummary(item_id, category, name)
            by_name[_normalize(name)].append(summary)
            by_category[category].append(summary)

        self._names = {
            key: tuple(sorted(values, key=lambda item: item.item_id))
            for key, values in by_name.items()
        }
        self._categories = {
            key: tuple(sorted(values, key=lambda item: item.item_id))
            for key, values in by_category.items()
        }
        self._initialized = True
        return self.status()

    def status(self) -> ItemCatalogStatus:
        return ItemCatalogStatus(
            initialized=self._initialized,
            item_count=len(self._items),
            category_counts=MappingProxyType(
                {category: len(items) for category, items in sorted(self._categories.items())}
            ),
        )

    def get(self, item_id: str) -> ItemDetail:
        self._require_initialized()
        key = str(item_id or "").strip()
        detail = self._items.get(key)
        if detail is None:
            raise ItemNotFoundError(f"未找到物品编号：{key or '<空>'}")
        return detail

    def find_by_name(self, name: str) -> tuple[ItemSummary, ...]:
        self._require_initialized()
        return self._names.get(_normalize(name), ())

    def inspect(self, identifier: str) -> ItemDetail:
        self._require_initialized()
        query = str(identifier or "").strip()
        if not query:
            raise ItemNotFoundError("物品编号或名称不能为空")
        if query in self._items:
            return self._items[query]
        candidates = self.find_by_name(query)
        if not candidates:
            raise ItemNotFoundError(f"未找到物品：{query}")
        if len(candidates) > 1:
            raise ItemNameAmbiguousError(query, candidates)
        return self._items[candidates[0].item_id]

    def category(self, category: str) -> tuple[ItemSummary, ...]:
        self._require_initialized()
        return self._categories.get(str(category or "").strip(), ())

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("物品查询微服务尚未初始化")


def _normalize(value: object) -> str:
    return "".join(str(value or "").split()).casefold()


def _required_text(value: object, path: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise JsonDataError(f"{path}必须是非空文本")
    return text


__all__ = ["ITEM_SECTION", "ItemCatalogService"]
