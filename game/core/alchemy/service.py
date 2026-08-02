"""兽宝为引、灵植为辅的正式炼药微服务。"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from typing import Any

from game.core.combat import CombatStatusSpec
from game.core.data import JsonDataService
from game.core.item import ItemService

from .contracts import (
    AlchemyError,
    AlchemyGradeBasis,
    AlchemyMaterial,
    AlchemyPlan,
    AlchemyRequest,
    AlchemyStatus,
    FurnaceMethod,
    MaterialAllocation,
    PreparedBattlePills,
    RecipeDefinition,
    VeinRequirement,
)

DIRECT_MODE = "本脉"
SIDE_MODE = "旁脉"


class AlchemyService:
    """解释炼药规则并生成精确耗材方案，不操作纳戒。"""

    def __init__(self, data: JsonDataService, items: ItemService) -> None:
        self._data = data
        self._items = items
        self._grades: dict[str, int] = {}
        self._grades_by_rank: dict[int, str] = {}
        self._veins: dict[str, tuple[str, str]] = {}
        self._furnaces: dict[str, FurnaceMethod] = {}
        self._recipes: dict[str, RecipeDefinition] = {}
        self._guide_pools: dict[str, frozenset[str]] = {}
        self._guide_category = ""
        self._guide_item_count = 0
        self._guides_per_batch = 0
        self._direct_material_count = 0
        self._side_material_count = 0
        self._same_material_limit = 0
        self._side_substitution_limit = 0
        self._output_count = 0
        self._grade_step_cost = 0
        self._maximum_output_grade = ""
        self._battle_pill_slot_limit = 0
        self._battle_pill_repeat = ""
        self._strength_slots: dict[int, int] = {}

    def initialize(self) -> AlchemyStatus:
        if self._recipes:
            raise RuntimeError("炼药微服务已经初始化")
        if not self._items.status().initialized:
            raise RuntimeError("物品微服务必须先于炼药微服务启动")
        rules = self._data.dataset("炼药规则")
        self._load_grades()
        self._load_general_rules(_mapping(rules.get("丹则"), "丹则"))
        self._load_veins(_sequence(rules.get("归脉"), "归脉"))
        self._load_furnaces(_sequence(rules.get("炉法"), "炉法"))
        self._load_recipes(_mapping(rules.get("战丹"), "战丹规则"))
        return self.status()

    def status(self) -> AlchemyStatus:
        return AlchemyStatus(
            initialized=bool(self._recipes),
            recipe_count=len(self._recipes),
            furnace_method_count=len(self._furnaces),
            material_pool_count=len(self._veins),
            guide_count=self._guide_item_count,
        )

    def recipes(self) -> tuple[RecipeDefinition, ...]:
        self._require_initialized()
        return tuple(self._recipes.values())

    def recipe(self, identity: str) -> RecipeDefinition:
        self._require_initialized()
        key = _text(identity, "丹方编号")
        try:
            return self._recipes[key]
        except KeyError as exc:
            raise AlchemyError(f"丹方不存在：{key}") from exc

    def furnace_methods(self) -> tuple[FurnaceMethod, ...]:
        self._require_initialized()
        return tuple(self._furnaces.values())

    def furnace_method(self, name: str) -> FurnaceMethod:
        self._require_initialized()
        key = _text(name, "炉法名称")
        try:
            return self._furnaces[key]
        except KeyError as exc:
            raise AlchemyError(f"炉法不存在：{key}") from exc

    def plan(self, request: AlchemyRequest) -> AlchemyPlan:
        recipe = self.recipe(request.recipe_id)
        guides = tuple(
            self._validate_material(value, "药引") for value in request.guides
        )
        if len(guides) != self._guides_per_batch:
            raise AlchemyError(f"每炉需要 {self._guides_per_batch} 味药引")
        for guide in guides:
            guide_item = self._items.item(guide.item_id)
            if guide_item.category != self._guide_category:
                raise AlchemyError(f"药引必须是{self._guide_category}")
            if guide.item_id not in self._guide_pools[recipe.guide_pool]:
                raise AlchemyError(f"药引不属于丹方药引池：{guide.item_id}")
            self._require_grade(guide.grade, recipe.minimum_guide_grade, "药引")

        auxiliaries = tuple(
            self._validate_material(value, "辅材") for value in request.auxiliaries
        )
        identities = tuple(value.item_id for value in auxiliaries)
        for identity in set(identities):
            if identities.count(identity) > self._same_material_limit:
                raise AlchemyError(
                    f"同一味灵植每炉最多占位 {self._same_material_limit} 次"
                )
        for material in auxiliaries:
            item = self._items.item(material.item_id)
            if item.category != "灵植":
                raise AlchemyError(f"辅材必须是灵植：{material.item_id}")
            if item.source_pool not in self._veins:
                raise AlchemyError(f"灵植没有归脉：{material.item_id}")
            self._require_grade(material.grade, recipe.minimum_auxiliary_grade, "辅材")

        furnace = self._furnaces[recipe.furnace_method]
        required_slots = tuple(
            requirement.vein
            for requirement in furnace.requirements
            for _ in range(requirement.count)
        )
        allocations = self._allocate(required_slots, auxiliaries)
        if allocations is None:
            raise AlchemyError("所选灵植不能满足炉法药脉")
        output_grade = self._output_grade(recipe, guides, auxiliaries)
        return AlchemyPlan(
            recipe=recipe,
            guides=guides,
            allocations=allocations,
            output_item_id=recipe.output_item_id,
            output_count=recipe.output_count,
            output_grade=output_grade,
            grade_basis=AlchemyGradeBasis(
                minimum_guide_grade=recipe.minimum_guide_grade,
                minimum_auxiliary_grade=recipe.minimum_auxiliary_grade,
                guide_grades=tuple(value.grade for value in guides),
                auxiliary_grades=tuple(value.grade for value in auxiliaries),
            ),
        )

    def prepare_battle_pills(
        self,
        item_ids: Sequence[str],
        *,
        source_id: str,
    ) -> PreparedBattlePills:
        self._require_initialized()
        source = _text(source_id, "战丹寄存者编号")
        identities = tuple(_text(value, "战丹编号") for value in item_ids)
        if self._battle_pill_repeat == "禁止" and len(identities) != len(
            set(identities)
        ):
            raise AlchemyError("同一名参战者不能重复寄存同一枚战丹")
        statuses: list[CombatStatusSpec] = []
        used_slots = 0
        for identity in identities:
            item = self._items.item(identity)
            effect = item.use_effect
            if effect is None or effect.executor != "寄存战丹":
                raise AlchemyError(f"物品不是战丹：{identity}")
            if item.strength is None or item.strength not in self._strength_slots:
                raise AlchemyError(f"战丹缺少有效强度：{identity}")
            state = effect.battle_state
            if state is None or state.duration_unit != "整场战斗":
                raise AlchemyError(f"战丹必须提供整场战斗状态：{identity}")
            slots = self._strength_slots[item.strength]
            used_slots += slots
            statuses.append(
                CombatStatusSpec(
                    name=state.name,
                    category=state.category,
                    remaining_actions=state.remaining_actions,
                    duration_unit=state.duration_unit,
                    modifiers=state.modifiers,
                    tags=state.tags,
                    mechanism_ids=effect.battle_mechanisms,
                    source=source,
                    source_name=item.name,
                    metadata=(
                        ("战丹编号", identity),
                        ("强度", item.strength),
                        ("丹位", slots),
                    ),
                )
            )
        if used_slots > self._battle_pill_slot_limit:
            raise AlchemyError(
                f"寄存战丹占用 {used_slots} 个丹位，超过上限 {self._battle_pill_slot_limit}"
            )
        return PreparedBattlePills(
            item_ids=identities,
            used_slots=used_slots,
            statuses=tuple(statuses),
        )

    def _load_grades(self) -> None:
        definitions = self._data.dataset("基础定义")
        for raw in _sequence(definitions.get("品级"), "品级定义"):
            row = _mapping(raw, "品级定义")
            identity = _text(row.get("编号"), "品级编号")
            rank = _positive_int(row.get("阶序"), f"品级 {identity} 阶序")
            if identity in self._grades or rank in self._grades.values():
                raise AlchemyError("品级编号和阶序必须唯一")
            self._grades[identity] = rank
            self._grades_by_rank[rank] = identity

    def _load_general_rules(self, rules: Mapping[str, Any]) -> None:
        _expect_fields(
            rules,
            required={"药引", "辅材", "成丹", "战丹"},
            optional=set(),
            label="丹则",
        )
        guide = _mapping(rules.get("药引"), "药引规则")
        _expect_fields(
            guide,
            required={"类别", "每炉数量"},
            optional=set(),
            label="药引规则",
        )
        self._guide_category = _text(guide.get("类别"), "药引类别")
        self._guides_per_batch = _positive_int(guide.get("每炉数量"), "每炉药引数量")
        auxiliaries = _mapping(rules.get("辅材"), "辅材规则")
        _expect_fields(
            auxiliaries,
            required={
                "取材依据",
                "本脉折算",
                "旁脉折算",
                "同一灵植最多占位",
                "旁脉替代上限",
            },
            optional=set(),
            label="辅材规则",
        )
        if _text(auxiliaries.get("取材依据"), "辅材取材依据") != "炉法.辅材":
            raise AlchemyError("辅材取材依据必须是炉法.辅材")
        self._direct_material_count = _positive_int(
            auxiliaries.get("本脉折算"), "本脉折算"
        )
        self._side_material_count = _positive_int(
            auxiliaries.get("旁脉折算"), "旁脉折算"
        )
        self._same_material_limit = _positive_int(
            auxiliaries.get("同一灵植最多占位"), "同一灵植最多占位"
        )
        self._side_substitution_limit = _nonnegative_int(
            auxiliaries.get("旁脉替代上限"), "旁脉替代上限"
        )
        output = _mapping(rules.get("成丹"), "成丹规则")
        _expect_fields(
            output,
            required={"基础数量", "品级"},
            optional=set(),
            label="成丹规则",
        )
        self._output_count = _positive_int(output.get("基础数量"), "成丹基础数量")
        grade = _mapping(output.get("品级"), "成丹品级规则")
        _expect_fields(
            grade,
            required={"算法", "每阶所需余量", "最高品级"},
            optional=set(),
            label="成丹品级规则",
        )
        if _text(grade.get("算法"), "成丹品级算法") != "最低余量进阶":
            raise AlchemyError("不支持的成丹品级算法")
        self._grade_step_cost = _positive_int(
            grade.get("每阶所需余量"), "成丹每阶所需余量"
        )
        self._maximum_output_grade = _grade(
            grade.get("最高品级"), self._grades, "成丹最高品级"
        )
        battle = _mapping(rules.get("战丹"), "战丹规则")
        _expect_fields(
            battle,
            required={
                "丹位上限",
                "同丹重复",
                "服用后",
                "生效时点",
                "清除时点",
                "中止战斗",
                "测试战斗",
            },
            optional=set(),
            label="战丹规则",
        )
        self._battle_pill_slot_limit = _positive_int(
            battle.get("丹位上限"), "战丹丹位上限"
        )
        self._battle_pill_repeat = _text(battle.get("同丹重复"), "战丹重复规则")
        if self._battle_pill_repeat not in {"允许", "禁止"}:
            raise AlchemyError(f"未知战丹重复规则：{self._battle_pill_repeat}")

    def _load_veins(self, rows: Sequence[Any]) -> None:
        for raw in rows:
            row = _mapping(raw, "归脉")
            _expect_fields(
                row,
                required={"灵植池", "本脉", "旁脉"},
                optional=set(),
                label="归脉",
            )
            pool = _text(row.get("灵植池"), "灵植池")
            primary = _text(row.get("本脉"), f"{pool} 本脉")
            side = _text(row.get("旁脉"), f"{pool} 旁脉")
            if primary == side:
                raise AlchemyError(f"灵植池本脉与旁脉不能相同：{pool}")
            if pool in self._veins:
                raise AlchemyError(f"灵植池重复归脉：{pool}")
            members = self._data.pool_members((pool,), "物品")
            if not members or any(
                self._items.item(value).category != "灵植" for value in members
            ):
                raise AlchemyError(f"归脉池不是纯灵植池：{pool}")
            self._veins[pool] = (primary, side)

    def _load_furnaces(self, rows: Sequence[Any]) -> None:
        for raw in rows:
            row = _mapping(raw, "炉法")
            _expect_fields(
                row,
                required={"名称", "炉势", "辅材"},
                optional=set(),
                label="炉法",
            )
            name = _text(row.get("名称"), "炉法名称")
            requirements = tuple(
                VeinRequirement(
                    vein=_text(value.get("药脉"), f"炉法 {name} 药脉"),
                    count=_positive_int(value.get("味数"), f"炉法 {name} 味数"),
                )
                for value in (
                    _strict_furnace_requirement(item, name)
                    for item in _sequence(row.get("辅材"), f"炉法 {name} 辅材")
                )
            )
            if not requirements:
                raise AlchemyError(f"炉法没有辅材：{name}")
            if name in self._furnaces:
                raise AlchemyError(f"炉法名称重复：{name}")
            self._furnaces[name] = FurnaceMethod(
                name=name,
                description=_text(row.get("炉势"), f"炉法 {name} 炉势"),
                requirements=requirements,
            )

    def _load_recipes(self, battle_rules: Mapping[str, Any]) -> None:
        _expect_fields(
            battle_rules,
            required={"强度规则", "炼制难度规则"},
            optional=set(),
            label="战丹规则",
        )
        strength_rules = {
            _positive_int(row.get("强度"), "战丹强度"): (
                _positive_int(row.get("丹位"), "战丹丹位"),
                {
                    _positive_int(value, "允许炼制难度")
                    for value in _sequence(row.get("允许炼制难度"), "允许炼制难度")
                },
            )
            for row in (
                _strict_strength_rule(value)
                for value in _sequence(battle_rules.get("强度规则"), "战丹强度规则")
            )
        }
        difficulty_rules = {
            _positive_int(row.get("炼制难度"), "炼制难度"): row
            for row in (
                _strict_difficulty_rule(value)
                for value in _sequence(battle_rules.get("炼制难度规则"), "炼制难度规则")
            )
        }
        for identity, raw in self._data.entities("丹方").items():
            _expect_fields(
                raw,
                required={"编号", "名称", "强度", "炼制难度", "药引池", "炉法", "成丹"},
                optional=set(),
                label=f"丹方 {identity}",
            )
            strength = _positive_int(raw.get("强度"), f"丹方 {identity} 强度")
            difficulty = _positive_int(raw.get("炼制难度"), f"丹方 {identity} 炼制难度")
            if difficulty not in strength_rules.get(strength, (0, set()))[1]:
                raise AlchemyError(f"丹方 {identity} 强度与炼制难度不兼容")
            difficulty_rule = difficulty_rules.get(difficulty)
            if difficulty_rule is None:
                raise AlchemyError(f"丹方 {identity} 炼制难度没有规则")
            guide_grade = _grade(
                difficulty_rule.get("最低药引品级"), self._grades, "最低药引品级"
            )
            auxiliary_grade = _grade(
                difficulty_rule.get("最低辅材品级"), self._grades, "最低辅材品级"
            )
            furnace_name = _text(raw.get("炉法"), f"丹方 {identity} 炉法")
            if furnace_name not in self._furnaces:
                raise AlchemyError(f"丹方 {identity} 引用未知炉法：{furnace_name}")
            total = sum(
                value.count for value in self._furnaces[furnace_name].requirements
            )
            range_rule = _mapping(difficulty_rule.get("辅材总味数"), "辅材总味数规则")
            if not (
                _positive_int(range_rule.get("最少"), "辅材最少味数")
                <= total
                <= _positive_int(range_rule.get("最多"), "辅材最多味数")
            ):
                raise AlchemyError(f"丹方 {identity} 炉法味数与难度不一致")
            guide_pool = _text(raw.get("药引池"), f"丹方 {identity} 药引池")
            if guide_pool not in self._guide_pools:
                members = frozenset(self._data.pool_members((guide_pool,), "物品"))
                if not members:
                    raise AlchemyError(f"药引池为空：{guide_pool}")
                self._guide_pools[guide_pool] = members
            output_id = _text(raw.get("成丹"), f"丹方 {identity} 成丹编号")
            output_item = self._items.item(output_id)
            if output_item.category != "丹药":
                raise AlchemyError(f"丹方 {identity} 成丹不是丹药")
            if output_item.strength != strength:
                raise AlchemyError(f"丹方 {identity} 强度与成丹不一致")
            self._recipes[identity] = RecipeDefinition(
                identity=identity,
                name=_text(raw.get("名称"), f"丹方 {identity} 名称"),
                strength=strength,
                difficulty=difficulty,
                minimum_guide_grade=guide_grade,
                minimum_auxiliary_grade=auxiliary_grade,
                guide_pool=guide_pool,
                furnace_method=furnace_name,
                output_item_id=output_id,
                output_count=self._output_count,
            )
        self._guide_item_count = len(set().union(*self._guide_pools.values()))
        self._strength_slots = {
            strength: slots
            for strength, (slots, _difficulties) in strength_rules.items()
        }

    def _allocate(
        self,
        required_slots: tuple[str, ...],
        materials: tuple[AlchemyMaterial, ...],
    ) -> tuple[MaterialAllocation, ...] | None:
        veins = tuple(
            self._veins[self._items.item(material.item_id).source_pool]
            for material in materials
        )

        def search(
            slot_index: int,
            unused: tuple[int, ...],
            side_used: int,
            allocations: tuple[MaterialAllocation, ...],
        ) -> tuple[MaterialAllocation, ...] | None:
            if slot_index == len(required_slots):
                if not unused:
                    return tuple(
                        sorted(allocations, key=lambda value: value.material.item_id)
                    )
                return None
            required = required_slots[slot_index]
            direct_candidates = [
                index for index in unused if veins[index][0] == required
            ]
            for group in itertools.combinations(
                direct_candidates, self._direct_material_count
            ):
                result = search(
                    slot_index + 1,
                    tuple(value for value in unused if value not in group),
                    side_used,
                    allocations
                    + tuple(
                        MaterialAllocation(
                            material=materials[index],
                            required_vein=required,
                            mode=DIRECT_MODE,
                        )
                        for index in group
                    ),
                )
                if result is not None:
                    return result
            if side_used >= self._side_substitution_limit:
                return None
            candidates = [index for index in unused if veins[index][1] == required]
            for group in itertools.combinations(candidates, self._side_material_count):
                result = search(
                    slot_index + 1,
                    tuple(value for value in unused if value not in group),
                    side_used + 1,
                    allocations
                    + tuple(
                        MaterialAllocation(
                            material=materials[index],
                            required_vein=required,
                            mode=SIDE_MODE,
                        )
                        for index in group
                    ),
                )
                if result is not None:
                    return result
            return None

        return search(0, tuple(range(len(materials))), 0, ())

    def _output_grade(
        self,
        recipe: RecipeDefinition,
        guides: tuple[AlchemyMaterial, ...],
        auxiliaries: tuple[AlchemyMaterial, ...],
    ) -> str:
        base_rank = max(
            self._grades[recipe.minimum_guide_grade],
            self._grades[recipe.minimum_auxiliary_grade],
        )
        margins = [
            self._grades[value.grade] - self._grades[recipe.minimum_guide_grade]
            for value in guides
        ]
        margins.extend(
            self._grades[value.grade] - self._grades[recipe.minimum_auxiliary_grade]
            for value in auxiliaries
        )
        advance = min(margins) // self._grade_step_cost
        maximum_rank = self._grades[self._maximum_output_grade]
        return self._grades_by_rank[min(base_rank + advance, maximum_rank)]

    def _validate_material(self, value: AlchemyMaterial, label: str) -> AlchemyMaterial:
        item_id = _text(value.item_id, f"{label}编号")
        grade = _grade(value.grade, self._grades, f"{label}品级")
        self._items.item(item_id)
        return AlchemyMaterial(item_id=item_id, grade=grade)

    def _require_grade(self, actual: str, minimum: str, label: str) -> None:
        if self._grades[actual] < self._grades[minimum]:
            raise AlchemyError(f"{label}品级不足：需要 {minimum}，实际 {actual}")

    def _require_initialized(self) -> None:
        if not self._recipes:
            raise RuntimeError("炼药微服务尚未初始化")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AlchemyError(f"{label} 必须是对象")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AlchemyError(f"{label} 必须是列表")
    return value


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise AlchemyError(f"{label} 不能为空")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AlchemyError(f"{label} 必须是非负整数")
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result < 1:
        raise AlchemyError(f"{label} 必须大于 0")
    return result


def _grade(value: Any, grades: Mapping[str, int], label: str) -> str:
    result = _text(value, label)
    if result not in grades:
        raise AlchemyError(f"{label}不存在：{result}")
    return result


def _expect_fields(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing:
        raise AlchemyError(f"{label} 缺少字段：{'、'.join(sorted(missing))}")
    if unknown:
        raise AlchemyError(f"{label} 存在未知字段：{'、'.join(sorted(unknown))}")


def _strict_furnace_requirement(value: Any, name: str) -> Mapping[str, Any]:
    row = _mapping(value, f"炉法 {name} 辅材")
    _expect_fields(
        row,
        required={"药脉", "味数"},
        optional=set(),
        label=f"炉法 {name} 辅材",
    )
    return row


def _strict_strength_rule(value: Any) -> Mapping[str, Any]:
    row = _mapping(value, "战丹强度规则")
    _expect_fields(
        row,
        required={"强度", "丹位", "允许炼制难度"},
        optional=set(),
        label="战丹强度规则",
    )
    return row


def _strict_difficulty_rule(value: Any) -> Mapping[str, Any]:
    row = _mapping(value, "炼制难度规则")
    _expect_fields(
        row,
        required={"炼制难度", "辅材总味数", "最低药引品级", "最低辅材品级"},
        optional=set(),
        label="炼制难度规则",
    )
    range_rule = _mapping(row.get("辅材总味数"), "辅材总味数规则")
    _expect_fields(
        range_rule,
        required={"最少", "最多"},
        optional=set(),
        label="辅材总味数规则",
    )
    return row


__all__ = ["DIRECT_MODE", "SIDE_MODE", "AlchemyService"]
