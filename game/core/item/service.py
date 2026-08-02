"""只解释正式物品 JSON 的公共微服务。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from game.core.data import JsonDataService

from .contracts import (
    ItemBattleState,
    ItemCategory,
    ItemDataError,
    ItemDefinition,
    ItemMedicineDefinition,
    ItemStatus,
    ItemUseEffect,
)

BASE_ITEM_FIELDS = frozenset({"编号", "名称", "说明", "权重", "参考价"})
EFFECT_EXECUTORS = frozenset({"恢复资源", "增加经验", "寄存战丹"})


class ItemService:
    """提供物品分类、定义和使用效果，不保存物品实例。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._categories: dict[str, ItemCategory] = {}
        self._category_fields: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
        self._effect_rules: dict[str, Mapping[str, Any]] = {}
        self._items: dict[str, ItemDefinition] = {}

    def initialize(self) -> ItemStatus:
        if self._categories:
            raise RuntimeError("物品微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于物品微服务启动")
        raw_categories = self._data.dataset("物品规则").get("分类")
        for raw in _sequence(raw_categories, "物品分类"):
            row = _mapping(raw, "物品分类")
            _expect_fields(
                row,
                required={"类别", "可堆叠", "必填字段", "可选字段"},
                optional=set(),
                label="物品分类",
            )
            name = _text(row.get("类别"), "物品类别")
            stackable = row.get("可堆叠")
            if not isinstance(stackable, bool):
                raise ItemDataError(f"物品类别 {name} 的可堆叠必须是布尔值")
            if name in self._categories:
                raise ItemDataError(f"物品类别重复：{name}")
            self._categories[name] = ItemCategory(name=name, stackable=stackable)
            required = frozenset(
                _strings(row.get("必填字段", ()), f"物品类别 {name} 必填字段")
            )
            optional = frozenset(
                _strings(row.get("可选字段", ()), f"物品类别 {name} 可选字段")
            )
            if required & optional:
                raise ItemDataError(f"物品类别 {name} 的必填字段与可选字段不能重叠")
            self._category_fields[name] = (required, optional)

        for raw in _sequence(
            self._data.dataset("物品定义").get("使用效果"), "使用效果定义"
        ):
            row = _mapping(raw, "使用效果定义")
            _expect_fields(
                row,
                required={"类型", "执行器", "必填字段"},
                optional={"可选字段", "资源", "目标"},
                label="使用效果定义",
            )
            effect_type = _text(row.get("类型"), "使用效果类型")
            executor = _text(row.get("执行器"), f"使用效果 {effect_type} 执行器")
            if executor not in EFFECT_EXECUTORS:
                raise ItemDataError(
                    f"使用效果 {effect_type} 的执行器不受支持：{executor}"
                )
            if effect_type in self._effect_rules:
                raise ItemDataError(f"使用效果类型重复：{effect_type}")
            self._effect_rules[effect_type] = row

        names: set[str] = set()
        for identity in self._data.entities("物品"):
            record = self._data.entity_record("物品", identity)
            raw = record.value
            category = record.number_category
            if category not in self._categories:
                raise ItemDataError(f"物品 {identity} 使用未知类别：{category}")
            required, optional = self._category_fields[category]
            _expect_fields(
                raw,
                required=BASE_ITEM_FIELDS | required,
                optional=optional,
                label=f"物品 {identity}",
            )
            name = _text(raw.get("名称"), f"物品 {identity} 名称")
            if name in names:
                raise ItemDataError(f"物品名称重复：{name}")
            names.add(name)
            use_effect = self._effect(raw.get("使用效果"), identity)
            strength = (
                _positive_int(raw.get("强度"), f"物品 {identity} 强度")
                if "强度" in raw
                else None
            )
            if use_effect is not None and use_effect.executor == "寄存战丹":
                if strength is None:
                    raise ItemDataError(f"战丹 {identity} 必须声明强度")
            elif strength is not None:
                raise ItemDataError(f"非战丹物品 {identity} 不能声明强度")
            self._items[identity] = ItemDefinition(
                identity=identity,
                category=category,
                name=name,
                description=_text(raw.get("说明"), f"物品 {identity} 说明"),
                weight=_positive_int(raw.get("权重"), f"物品 {identity} 权重"),
                reference_price=_nonnegative_int(
                    raw.get("参考价"), f"物品 {identity} 参考价"
                ),
                source_pool=record.source_file,
                stackable=self._categories[category].stackable,
                use_effect=use_effect,
                strength=strength,
            )
        return self.status()

    def status(self) -> ItemStatus:
        return ItemStatus(
            initialized=bool(self._categories),
            category_count=len(self._categories),
            item_count=len(self._items),
            usable_item_count=sum(
                item.use_effect is not None for item in self._items.values()
            ),
        )

    def categories(self) -> tuple[ItemCategory, ...]:
        self._require_initialized()
        return tuple(self._categories.values())

    def category(self, name: str) -> ItemCategory:
        self._require_initialized()
        key = _text(name, "物品类别")
        try:
            return self._categories[key]
        except KeyError as exc:
            raise ItemDataError(f"物品类别不存在：{key}") from exc

    def items(self, category: str | None = None) -> tuple[ItemDefinition, ...]:
        self._require_initialized()
        if category is None:
            return tuple(self._items.values())
        category_name = self.category(category).name
        return tuple(
            item for item in self._items.values() if item.category == category_name
        )

    def item(self, identity: str) -> ItemDefinition:
        self._require_initialized()
        key = _text(identity, "物品编号")
        try:
            return self._items[key]
        except KeyError as exc:
            raise ItemDataError(f"物品不存在：{key}") from exc

    def medicine(self, identity: str) -> ItemMedicineDefinition:
        item = self.item(identity)
        effect = item.use_effect
        if effect is None or effect.executor != "恢复资源":
            raise ItemDataError(f"物品不是恢复丹：{item.identity}")
        if effect.resource is None or effect.recovery_percent is None:
            raise ItemDataError(f"恢复丹定义不完整：{item.identity}")
        return ItemMedicineDefinition(
            identity=item.identity,
            resource=effect.resource,
            recovery_percent=effect.recovery_percent,
        )

    def medicines(
        self, identities: Sequence[str]
    ) -> tuple[ItemMedicineDefinition, ...]:
        result = tuple(self.medicine(identity) for identity in identities)
        if len({value.identity for value in result}) != len(result):
            raise ItemDataError("恢复丹编号不能重复")
        return result

    def _effect(self, value: Any, identity: str) -> ItemUseEffect | None:
        if value is None:
            return None
        raw = _mapping(value, f"物品 {identity} 使用效果")
        effect_type = _text(raw.get("类型"), f"物品 {identity} 使用效果类型")
        rule = self._effect_rules.get(effect_type)
        if rule is None:
            raise ItemDataError(f"物品 {identity} 使用未知效果：{effect_type}")
        required = frozenset(
            _strings(rule.get("必填字段"), f"使用效果 {effect_type} 必填字段")
        )
        optional = frozenset(
            _strings(rule.get("可选字段", ()), f"使用效果 {effect_type} 可选字段")
        )
        _expect_fields(
            raw,
            required={"类型"} | required,
            optional=optional,
            label=f"物品 {identity} 使用效果",
        )
        executor = _text(rule.get("执行器"), f"使用效果 {effect_type} 执行器")
        if executor == "恢复资源":
            return ItemUseEffect(
                effect_type=effect_type,
                executor=executor,
                resource=_text(rule.get("资源"), f"使用效果 {effect_type} 资源"),
                recovery_percent=_positive_int(
                    raw.get("恢复百分比"), f"物品 {identity} 恢复百分比"
                ),
            )
        if executor == "增加经验":
            return ItemUseEffect(
                effect_type=effect_type,
                executor=executor,
                experience_target=_text(
                    rule.get("目标"), f"使用效果 {effect_type} 目标"
                ),
                experience=_positive_int(raw.get("经验"), f"物品 {identity} 经验"),
            )
        state = _mapping(raw.get("战前状态"), f"物品 {identity} 战前状态")
        _expect_fields(
            state,
            required={"名称", "类别", "剩余行动", "持续单位", "属性", "标签"},
            optional=set(),
            label=f"物品 {identity} 战前状态",
        )
        modifiers = _mapping(state.get("属性"), f"物品 {identity} 战前状态属性")
        return ItemUseEffect(
            effect_type=effect_type,
            executor=executor,
            battle_mechanisms=_strings(
                raw.get("战斗机制", ()), f"物品 {identity} 战斗机制"
            ),
            battle_state=ItemBattleState(
                name=_text(state.get("名称"), f"物品 {identity} 战前状态名称"),
                category=_text(state.get("类别"), f"物品 {identity} 战前状态类别"),
                remaining_actions=_nonnegative_int(
                    state.get("剩余行动"), f"物品 {identity} 战前状态剩余行动"
                ),
                duration_unit=_text(
                    state.get("持续单位"), f"物品 {identity} 战前状态持续单位"
                ),
                modifiers=tuple(
                    sorted(
                        (str(name), _number(amount, f"物品 {identity} 状态属性"))
                        for name, amount in modifiers.items()
                    )
                ),
                tags=_strings(state.get("标签", ()), f"物品 {identity} 状态标签"),
            ),
        )

    def _require_initialized(self) -> None:
        if not self._categories:
            raise RuntimeError("物品微服务尚未初始化")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ItemDataError(f"{label} 必须是对象")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ItemDataError(f"{label} 必须是列表")
    return value


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ItemDataError(f"{label} 不能为空")
    return result


def _strings(value: Any, label: str) -> tuple[str, ...]:
    result = tuple(_text(item, label) for item in _sequence(value, label))
    if len(result) != len(set(result)):
        raise ItemDataError(f"{label} 不能重复")
    return result


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ItemDataError(f"{label} 必须是数值")
    return float(value)


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ItemDataError(f"{label} 必须是非负整数")
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result < 1:
        raise ItemDataError(f"{label} 必须大于 0")
    return result


def _expect_fields(
    value: Mapping[str, Any],
    *,
    required: set[str] | frozenset[str],
    optional: set[str] | frozenset[str],
    label: str,
) -> None:
    missing = set(required) - set(value)
    unknown = set(value) - set(required) - set(optional)
    if missing:
        raise ItemDataError(f"{label} 缺少字段：{'、'.join(sorted(missing))}")
    if unknown:
        raise ItemDataError(f"{label} 存在未知字段：{'、'.join(sorted(unknown))}")


__all__ = ["ItemService"]
