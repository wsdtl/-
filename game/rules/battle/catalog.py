"""战报 JSON 的只读内存目录。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any


_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True, slots=True)
class BattleReportCatalog:
    """校验一次战报配置，后续标准化和展示只查询这个目录。"""

    raw: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BattleReportCatalog":
        raw = deepcopy(dict(value))
        catalog = cls(raw)
        catalog._validate()
        return catalog

    @property
    def report_schema(self) -> str:
        return str(self.protocol["战报"])

    @property
    def presentation_schema(self) -> str:
        return str(self.protocol["展示"])

    @property
    def presentation_version(self) -> int:
        return int(self.protocol["展示版本"])

    @property
    def game_name(self) -> str:
        return str(self.raw["游戏名称"])

    @property
    def protocol(self) -> Mapping[str, Any]:
        return _mapping(self.raw, "协议")

    @property
    def visual(self) -> Mapping[str, Any]:
        return _mapping(self.raw, "视觉")

    @property
    def normalization(self) -> Mapping[str, Any]:
        return _mapping(self.raw, "标准化")

    @property
    def presentation(self) -> Mapping[str, Any]:
        return _mapping(self.raw, "展示")

    @property
    def system(self) -> Mapping[str, Any]:
        return _mapping(self.visual, "系统")

    @property
    def foreground(self) -> str:
        return str(self.visual["前景色"])

    @property
    def participant_colors(self) -> tuple[str, ...]:
        return tuple(str(value) for value in _sequence(self.visual, "参战者颜色"))

    @property
    def resources(self) -> Mapping[str, Mapping[str, Any]]:
        return _mapping(self.visual, "资源")

    @property
    def category_definitions(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(_mapping_value(value, "标准化.分类") for value in _sequence(self.normalization, "分类"))

    @property
    def ui(self) -> dict[str, Any]:
        return deepcopy(dict(_mapping(self.presentation, "界面")))

    @property
    def compact_hidden_kinds(self) -> frozenset[str]:
        return _strings(self.normalization, "紧凑隐藏类型")

    @property
    def system_kinds(self) -> frozenset[str]:
        return _strings(self.normalization, "系统类型")

    @property
    def percent_details(self) -> frozenset[str]:
        return _strings(self.normalization, "百分比明细")

    @property
    def multiplier_details(self) -> frozenset[str]:
        return _strings(self.normalization, "倍率明细")

    @property
    def percent_attributes(self) -> frozenset[str]:
        return _strings(self.normalization, "百分比属性")

    @property
    def attribute_summary(self) -> tuple[str, ...]:
        return tuple(_strings_in_order(self.normalization, "属性摘要"))

    @property
    def damage_steps(self) -> tuple[str, ...]:
        return tuple(_strings_in_order(self.normalization, "伤害步骤"))

    @property
    def damage_facts(self) -> frozenset[str]:
        return _strings(self.presentation, "伤害事实")

    @property
    def view_modes(self) -> list[dict[str, Any]]:
        return [deepcopy(dict(value)) for value in _sequence(self.normalization, "查看模式")]

    @property
    def participant_presentation(self) -> Mapping[str, Any]:
        return _mapping(self.presentation, "参战者")

    def normalized_category(self, kind: str) -> str:
        mapping = _mapping(self.normalization, "类型分类")
        return str(mapping.get(kind) or self.normalization["默认分类"])

    def normalized_category_definition(self, category_id: str) -> Mapping[str, Any]:
        for value in self.category_definitions:
            if value["id"] == category_id:
                return value
        raise KeyError(f"战报配置没有分类：{category_id}")

    def kind_label(self, kind: str) -> str:
        return str(_mapping(self.normalization, "类型名称").get(kind) or kind)

    def public_category(self, kind: str, normalized_category: str) -> str:
        direct = _mapping(self.presentation, "类型分类")
        normalized = _mapping(self.presentation, "战报分类")
        return str(
            direct.get(kind)
            or normalized.get(normalized_category)
            or self.presentation["默认分类"]
        )

    def event_tone(self, category: str, kind: str) -> str:
        direct = _mapping(self.presentation, "类型色调")
        categories = _mapping(self.presentation, "分类色调")
        return str(
            direct.get(kind)
            or categories.get(category)
            or self.presentation["默认色调"]
        )

    def dominant_tone(self, categories: Sequence[str]) -> str:
        present = set(categories)
        for category in _strings_in_order(self.presentation, "分类优先级"):
            if category in present:
                return category
        return str(self.presentation["默认分类"])

    def resource_key(self, label: str) -> str | None:
        value = _mapping(self.presentation, "资源键").get(label)
        return str(value) if value is not None else None

    def status_tone(self, category: str) -> str:
        return str(
            _mapping(self.presentation, "状态色调").get(category)
            or self.presentation["默认状态色调"]
        )

    def result_tone(self, code: str) -> str:
        return str(
            _mapping(self.presentation, "结果色调").get(code)
            or self.presentation["默认结果色调"]
        )

    def _validate(self) -> None:
        if not self.report_schema.strip() or not self.presentation_schema.strip():
            raise ValueError("战报配置缺少协议名称")
        if self.presentation_version < 1:
            raise ValueError("战报展示版本必须是正整数")
        if not self.game_name.strip():
            raise ValueError("战报配置缺少游戏名称")
        if not _COLOR.fullmatch(self.foreground):
            raise ValueError("战报前景色必须是六位十六进制颜色")
        if not self.participant_colors:
            raise ValueError("战报至少需要一种参战者颜色")
        for color in (*self.participant_colors, str(self.system["color"])):
            if not _COLOR.fullmatch(color):
                raise ValueError(f"战报颜色不合法：{color}")
        category_ids = [str(value.get("id") or "") for value in self.category_definitions]
        if len(category_ids) != len(set(category_ids)) or not all(category_ids):
            raise ValueError("战报标准分类标识不能为空或重复")
        default_category = str(self.normalization["默认分类"])
        if default_category not in category_ids:
            raise ValueError("战报默认分类没有对应定义")
        for resource_id in ("health", "spirit", "shield"):
            definition = _mapping(self.resources, resource_id)
            if not str(definition.get("label") or "").strip():
                raise ValueError(f"战报资源缺少名称：{resource_id}")
            if not _COLOR.fullmatch(str(definition.get("color") or "")):
                raise ValueError(f"战报资源颜色不合法：{resource_id}")
        ui = _mapping(self.presentation, "界面")
        for key in ("text", "modes", "filters", "snapshots"):
            if key not in ui:
                raise ValueError(f"战报界面配置缺少：{key}")


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _mapping_value(value.get(key), key)


def _mapping_value(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"战报配置必须是对象：{path}")
    return value


def _sequence(value: Mapping[str, Any], key: str) -> Sequence[Any]:
    result = value.get(key)
    if not isinstance(result, list | tuple):
        raise ValueError(f"战报配置必须是数组：{key}")
    return result


def _strings(value: Mapping[str, Any], key: str) -> frozenset[str]:
    return frozenset(_strings_in_order(value, key))


def _strings_in_order(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    result = tuple(str(item) for item in _sequence(value, key))
    if any(not item.strip() for item in result):
        raise ValueError(f"战报配置不能包含空值：{key}")
    return result


__all__ = ["BattleReportCatalog"]
