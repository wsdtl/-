from pathlib import Path

import pytest

from game.core.data import JsonDataService
from game.core.item_catalog import ItemCatalogService


@pytest.fixture
def catalog() -> ItemCatalogService:
    root = Path(__file__).resolve().parents[3]
    data = JsonDataService(root / "data")
    data.initialize()
    service = ItemCatalogService(data)
    service.initialize()
    return service


def test_inspect_item_by_id_returns_public_definition(catalog: ItemCatalogService) -> None:
    detail = catalog.inspect("100005")

    assert detail.item_id == "100005"
    assert detail.category == "丹药"
    assert detail.name == "小还丹"
    assert detail.fields["使用效果"]["类型"] == "恢复血气"
    assert "权重" not in detail.fields
    assert "参考价" not in detail.fields
    with pytest.raises(TypeError):
        detail.fields["使用效果"]["恢复百分比"] = 99


def test_inspect_item_by_name_returns_same_definition(catalog: ItemCatalogService) -> None:
    assert catalog.inspect("小还丹").item_id == "100005"


def test_category_indexes_cover_all_item_categories(catalog: ItemCatalogService) -> None:
    status = catalog.status()

    assert status.item_count == 941
    assert status.category_counts == {
        "丹药": 359,
        "灵植": 108,
        "灵矿": 108,
        "兽宝": 366,
    }


def test_unknown_item_returns_not_found(catalog: ItemCatalogService) -> None:
    with pytest.raises(ValueError, match="未找到物品"):
        catalog.inspect("不存在的物品")
