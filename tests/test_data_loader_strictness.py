"""正式 JSON 目录必须完整进入数据微服务索引。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from game.core.data import JsonDataError
from game.core.data.files import JsonDataReader


def test_unknown_content_path_stops_loading(tmp_path: Path) -> None:
    _write_rules(tmp_path, [_bootstrap_rule()])
    (tmp_path / "内容" / "未分类.json").write_text("[]\n", encoding="utf-8")

    with pytest.raises(JsonDataError, match="没有匹配的读取规则"):
        JsonDataReader(tmp_path).load_catalog()


def test_invalid_read_rule_manifest_stops_loading(tmp_path: Path) -> None:
    rule = _bootstrap_rule()
    _write_rules(tmp_path, [rule, dict(rule)])

    with pytest.raises(JsonDataError, match="重复路径"):
        JsonDataReader(tmp_path).load_catalog()


def test_world_documents_are_separated_by_json_read_rules() -> None:
    root = Path(__file__).resolve().parents[1] / "data"
    catalog = JsonDataReader(root).load_catalog()

    assert catalog.by_path["内容/世界/青岚州/青溪村/青溪村.json"].descriptor.dataset == "地点"
    assert catalog.by_path["内容/世界/青岚州/青溪村/青溪村道侣.json"].descriptor.dataset == "道侣"
    assert catalog.by_path["内容/世界/青岚州/青溪村/青溪村敌人.json"].descriptor.dataset == "敌人"


def _bootstrap_rule() -> dict[str, str]:
    return {
        "数据集": "数据读取",
        "数据名": "规则",
        "路径": "定义/数据读取规则.json",
        "文档形态": "对象",
    }


def _write_rules(root: Path, rules: list[dict[str, str]]) -> None:
    for scope in ("定义", "规则", "内容", "展示"):
        (root / scope).mkdir(exist_ok=True)
    value = {
        "作用域": ["定义", "规则", "内容", "展示"],
        "编号定义": "定义/数据读取规则.json",
        "文件名引用作用域": ["内容"],
        "资源池引用作用域": ["规则", "内容"],
        "资源池引用": {"功法池": "功法"},
        "读取规则": rules,
    }
    (root / "定义" / "数据读取规则.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
