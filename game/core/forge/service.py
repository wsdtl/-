"""兽宝为引、灵矿为辅的本命武器炼器微服务。"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from game.core.data import JsonDataService
from game.core.item import ItemService

from .contracts import (
    ForgeAllocation,
    ForgeError,
    ForgeLawDefinition,
    ForgeMaterial,
    ForgeMethod,
    ForgePlan,
    ForgeRequest,
    ForgeStatus,
    ForgeVeinRequirement,
    WeaponProfile,
    WeaponState,
    WeaponTier,
)

DIRECT_MODE = "本脉"
SIDE_MODE = "旁脉"


class ForgeService:
    """解释炼器 JSON，生成精确耗材方案，不操作背包或数据库。"""

    def __init__(self, data: JsonDataService, items: ItemService) -> None:
        self._data = data
        self._items = items
        self._grades: dict[str, int] = {}
        self._tiers: dict[str, WeaponTier] = {}
        self._tier_order: dict[str, int] = {}
        self._mineral_veins: dict[str, tuple[str, str]] = {}
        self._beast_veins: dict[str, str] = {}
        self._methods: dict[str, ForgeMethod] = {}
        self._laws: dict[str, ForgeLawDefinition] = {}
        self._initial_level = 0
        self._maximum_level = 0
        self._base_attack = 0.0
        self._attack_per_level = 0.0
        self._experience_power_base = 0
        self._experience_level_base = 0
        self._experience_power = 0.0
        self._experience_late: Mapping[str, Any] = {}
        self._slot_count = 0
        self._direct_material_count = 0
        self._side_material_count = 0
        self._same_mineral_limit = 0
        self._same_guide_limit = 0

    def initialize(self) -> ForgeStatus:
        if self._laws:
            raise RuntimeError("炼器微服务已经初始化")
        if not self._items.status().initialized:
            raise RuntimeError("物品微服务必须先于炼器微服务启动")
        rules = self._data.dataset("炼器规则")
        self._load_grades()
        self._load_weapon_rule(_mapping(rules.get("本命武器"), "本命武器规则"))
        self._load_general_rules(_mapping(rules.get("器则"), "器则"))
        self._load_mineral_veins(_sequence(rules.get("归脉"), "炼器归脉"))
        self._load_beast_veins(_sequence(rules.get("归引"), "炼器归引"))
        self._load_methods(_sequence(rules.get("铸法"), "铸法"))
        self._load_laws()
        return self.status()

    def status(self) -> ForgeStatus:
        return ForgeStatus(
            initialized=bool(self._laws),
            law_count=len(self._laws),
            method_count=len(self._methods),
            mineral_pool_count=len(self._mineral_veins),
            beast_pool_count=len(self._beast_veins),
            mineral_count=sum(
                len(self._data.pool_members((pool,), "物品"))
                for pool in self._mineral_veins
            ),
            beast_treasure_count=sum(
                len(self._data.pool_members((pool,), "物品"))
                for pool in self._beast_veins
            ),
        )

    def laws(self) -> tuple[ForgeLawDefinition, ...]:
        self._require_initialized()
        return tuple(self._laws.values())

    def law(self, identity: str) -> ForgeLawDefinition:
        self._require_initialized()
        key = _text(identity, "器律编号")
        try:
            return self._laws[key]
        except KeyError as exc:
            raise ForgeError(f"器律不存在：{key}") from exc

    def methods(self) -> tuple[ForgeMethod, ...]:
        self._require_initialized()
        return tuple(self._methods.values())

    def method(self, name: str) -> ForgeMethod:
        self._require_initialized()
        key = _text(name, "铸法名称")
        try:
            return self._methods[key]
        except KeyError as exc:
            raise ForgeError(f"铸法不存在：{key}") from exc

    def tiers(self) -> tuple[WeaponTier, ...]:
        self._require_initialized()
        return tuple(self._tiers.values())

    def tier_for_level(self, level: int) -> WeaponTier:
        self._require_initialized()
        actual = _positive_int(level, "本命武器等级")
        for tier in self._tiers.values():
            if tier.minimum_level <= actual <= tier.maximum_level:
                return tier
        raise ForgeError(f"本命武器等级超出范围：{actual}")

    def default_weapon(self) -> WeaponState:
        self._require_initialized()
        return WeaponState(level=self._initial_level, laws=(None,) * self._slot_count)

    def weapon_profile(self, state: WeaponState) -> WeaponProfile:
        weapon = self._validate_weapon(state)
        tier = self.tier_for_level(weapon.level)
        return WeaponProfile(
            level=weapon.level,
            experience=weapon.experience,
            tier=tier.name,
            attack=self._base_attack
            + (weapon.level - self._initial_level) * self._attack_per_level,
            open_slots=tier.open_slots,
            laws=weapon.laws,
        )

    def experience_needed(self, level: int) -> int:
        actual = _positive_int(level, "本命武器等级")
        if actual >= self._maximum_level:
            return 0
        base = math.floor(
            self._experience_power_base * (actual**self._experience_power)
            + self._experience_level_base * actual
        )
        start = _positive_int(self._experience_late.get("起始等级"), "经验后段起始等级")
        if actual <= start:
            return base
        span = _positive_int(self._experience_late.get("跨度"), "经验后段跨度")
        progress = max(0.0, (actual - start) / span)
        multiplier = (
            1
            + _nonnegative_number(self._experience_late.get("中段系数"), "经验中段系数")
            * progress
            ** _positive_number(self._experience_late.get("中段幂次"), "经验中段幂次")
            + _nonnegative_number(self._experience_late.get("高段系数"), "经验高段系数")
            * progress
            ** _positive_number(self._experience_late.get("高段幂次"), "经验高段幂次")
            + _nonnegative_number(self._experience_late.get("终段系数"), "经验终段系数")
            * progress
            ** _positive_number(self._experience_late.get("终段幂次"), "经验终段幂次")
        )
        return math.floor(base * multiplier)

    def add_experience(self, state: WeaponState, amount: int) -> WeaponState:
        weapon = self._validate_weapon(state)
        gained = _nonnegative_int(amount, "本命武器经验增量")
        level = weapon.level
        experience = weapon.experience + gained
        while level < self._maximum_level:
            required = self.experience_needed(level)
            if experience < required:
                break
            experience -= required
            level += 1
        if level == self._maximum_level:
            experience = 0
        return replace(weapon, level=level, experience=experience)

    def plan(self, request: ForgeRequest) -> ForgePlan:
        law = self.law(request.law_id)
        weapon = self._validate_weapon(request.weapon)
        weapon_tier = self.tier_for_level(weapon.level)
        law_tier = self._tiers[law.tier]
        if self._tier_order[weapon_tier.name] < self._tier_order[law_tier.name]:
            raise ForgeError(
                f"本命武器器阶不足：{law.name}需要{law_tier.name}，当前为{weapon_tier.name}"
            )
        slot = _positive_int(request.slot, "器律孔")
        if slot > weapon_tier.open_slots:
            raise ForgeError(f"器律孔 {slot} 尚未开放，当前只开放 {weapon_tier.open_slots} 孔")

        guides = tuple(self._validate_material(value, "兽引") for value in request.guides)
        self._validate_guides(law, law_tier, guides)
        auxiliaries = tuple(
            self._validate_material(value, "矿材") for value in request.auxiliaries
        )
        self._validate_auxiliaries(law_tier, auxiliaries)
        method = self._methods[law.forge_method]
        required_slots = tuple(
            requirement.vein
            for requirement in method.requirements
            for _ in range(requirement.count)
        )
        allocations = self._allocate(
            required_slots,
            auxiliaries,
            side_limit=law_tier.side_substitution_limit,
        )
        if allocations is None:
            raise ForgeError("所选灵矿不能满足铸法，或存在未被铸法消耗的投入")
        laws = list(weapon.laws)
        replaced = laws[slot - 1]
        laws[slot - 1] = law.identity
        forged = replace(weapon, laws=tuple(laws))
        return ForgePlan(
            law=law,
            guides=guides,
            allocations=allocations,
            slot=slot,
            replaced_law_id=replaced,
            weapon=forged,
        )

    def _load_grades(self) -> None:
        definitions = self._data.dataset("基础定义")
        for raw in _sequence(definitions.get("品级"), "品级定义"):
            row = _mapping(raw, "品级定义")
            identity = _text(row.get("编号"), "品级编号")
            rank = _positive_int(row.get("阶序"), f"品级 {identity} 阶序")
            if identity in self._grades or rank in self._grades.values():
                raise ForgeError("品级编号和阶序必须唯一")
            self._grades[identity] = rank

    def _load_weapon_rule(self, rule: Mapping[str, Any]) -> None:
        _expect_fields(
            rule,
            required={"初始等级", "等级上限", "基础攻击", "每级攻击", "经验"},
            optional=set(),
            label="本命武器规则",
        )
        self._initial_level = _positive_int(rule.get("初始等级"), "本命武器初始等级")
        self._maximum_level = _positive_int(rule.get("等级上限"), "本命武器等级上限")
        if self._maximum_level < self._initial_level:
            raise ForgeError("本命武器等级上限不能低于初始等级")
        self._base_attack = _nonnegative_number(rule.get("基础攻击"), "本命武器基础攻击")
        self._attack_per_level = _nonnegative_number(rule.get("每级攻击"), "本命武器每级攻击")
        experience = _mapping(rule.get("经验"), "本命武器经验")
        _expect_fields(
            experience,
            required={"幂次基数", "等级基数", "等级幂次", "后段"},
            optional=set(),
            label="本命武器经验",
        )
        self._experience_power_base = _positive_int(
            experience.get("幂次基数"), "本命武器经验幂次基数"
        )
        self._experience_level_base = _positive_int(
            experience.get("等级基数"), "本命武器经验等级基数"
        )
        self._experience_power = _positive_number(
            experience.get("等级幂次"), "本命武器经验等级幂次"
        )
        self._experience_late = _validate_experience_late(
            experience.get("后段"), "本命武器经验后段"
        )

    def _load_general_rules(self, rules: Mapping[str, Any]) -> None:
        _expect_fields(
            rules,
            required={"兽引", "辅材", "器阶", "覆炼"},
            optional=set(),
            label="器则",
        )
        guide = _mapping(rules.get("兽引"), "兽引规则")
        _expect_fields(
            guide,
            required={"类别", "同一兽宝最多占位", "匹配方式"},
            optional=set(),
            label="兽引规则",
        )
        if _text(guide.get("类别"), "兽引类别") != "兽宝":
            raise ForgeError("兽引类别必须是兽宝")
        if _text(guide.get("匹配方式"), "兽引匹配方式") != "逐位匹配兽脉":
            raise ForgeError("兽引必须逐位匹配兽脉")
        self._same_guide_limit = _positive_int(
            guide.get("同一兽宝最多占位"), "同一兽宝最多占位"
        )
        auxiliary = _mapping(rules.get("辅材"), "炼器辅材规则")
        _expect_fields(
            auxiliary,
            required={"类别", "取材依据", "本脉折算", "旁脉折算", "同一灵矿最多占位", "投入要求"},
            optional=set(),
            label="炼器辅材规则",
        )
        if _text(auxiliary.get("类别"), "炼器辅材类别") != "灵矿":
            raise ForgeError("炼器辅材类别必须是灵矿")
        if _text(auxiliary.get("取材依据"), "炼器取材依据") != "铸法.辅材":
            raise ForgeError("炼器辅材必须依据铸法.辅材")
        if _text(auxiliary.get("投入要求"), "炼器投入要求") != "全部投入必须恰好用于铸法":
            raise ForgeError("炼器投入必须全部被铸法消耗")
        self._direct_material_count = _positive_int(auxiliary.get("本脉折算"), "本脉折算")
        self._side_material_count = _positive_int(auxiliary.get("旁脉折算"), "旁脉折算")
        self._same_mineral_limit = _positive_int(
            auxiliary.get("同一灵矿最多占位"), "同一灵矿最多占位"
        )
        self._load_tiers(_sequence(rules.get("器阶"), "器阶规则"))
        overwrite = _mapping(rules.get("覆炼"), "覆炼规则")
        _expect_fields(
            overwrite,
            required={"器律孔总数", "器律孔编号", "未开放器律孔", "已有器律", "其他器律孔"},
            optional=set(),
            label="覆炼规则",
        )
        self._slot_count = _positive_int(overwrite.get("器律孔总数"), "器律孔总数")
        expected = {
            "器律孔编号": "从1开始",
            "未开放器律孔": "禁止锻造",
            "已有器律": "覆盖",
            "其他器律孔": "保持不变",
        }
        if any(overwrite.get(key) != value for key, value in expected.items()):
            raise ForgeError("覆炼规则必须明确单孔覆盖且保持其他器律孔")
        if max(tier.open_slots for tier in self._tiers.values()) != self._slot_count:
            raise ForgeError("最高器阶开放器律孔数量必须等于器律孔总数")

    def _load_tiers(self, rows: Sequence[Any]) -> None:
        previous_maximum = 0
        previous_slots = -1
        for index, raw in enumerate(rows):
            row = _mapping(raw, "器阶规则")
            _expect_fields(
                row,
                required={"名称", "等级范围", "开放器律孔", "兽引数量", "矿材份数", "旁脉替代上限", "最低兽宝品级", "最低灵矿品级"},
                optional=set(),
                label="器阶规则",
            )
            name = _text(row.get("名称"), "器阶名称")
            lower, upper = _range_pair(row.get("等级范围"), f"器阶 {name} 等级范围")
            open_slots = _nonnegative_int(row.get("开放器律孔"), f"器阶 {name} 开放器律孔")
            mineral_minimum, mineral_maximum = _range_pair(
                row.get("矿材份数"), f"器阶 {name} 矿材份数", allow_zero=True
            )
            if name in self._tiers or lower != previous_maximum + 1 or open_slots < previous_slots:
                raise ForgeError("器阶名称必须唯一，等级必须连续，开放器律孔不能倒退")
            tier = WeaponTier(
                name=name,
                minimum_level=lower,
                maximum_level=upper,
                open_slots=open_slots,
                guide_count=_nonnegative_int(row.get("兽引数量"), f"器阶 {name} 兽引数量"),
                minimum_mineral_slots=mineral_minimum,
                maximum_mineral_slots=mineral_maximum,
                side_substitution_limit=_nonnegative_int(
                    row.get("旁脉替代上限"), f"器阶 {name} 旁脉替代上限"
                ),
                minimum_guide_grade=_grade(
                    row.get("最低兽宝品级"), self._grades, f"器阶 {name} 最低兽宝品级"
                ),
                minimum_mineral_grade=_grade(
                    row.get("最低灵矿品级"), self._grades, f"器阶 {name} 最低灵矿品级"
                ),
            )
            self._tiers[name] = tier
            self._tier_order[name] = index
            previous_maximum = upper
            previous_slots = open_slots
        if previous_maximum != self._maximum_level:
            raise ForgeError("器阶没有覆盖完整的本命武器等级")

    def _load_mineral_veins(self, rows: Sequence[Any]) -> None:
        for raw in rows:
            row = _mapping(raw, "炼器归脉")
            _expect_fields(
                row,
                required={"灵矿池", "本脉", "旁脉"},
                optional=set(),
                label="炼器归脉",
            )
            pool = _text(row.get("灵矿池"), "灵矿池")
            primary = _text(row.get("本脉"), f"{pool} 本脉")
            side = _text(row.get("旁脉"), f"{pool} 旁脉")
            if primary == side or pool in self._mineral_veins:
                raise ForgeError(f"灵矿池归脉重复或本旁脉相同：{pool}")
            members = self._data.pool_members((pool,), "物品")
            if not members or any(self._items.item(value).category != "灵矿" for value in members):
                raise ForgeError(f"归脉池不是纯灵矿池：{pool}")
            self._mineral_veins[pool] = (primary, side)
        expected = {value.source_pool for value in self._items.items("灵矿")}
        if set(self._mineral_veins) != expected:
            raise ForgeError("炼器归脉没有完整覆盖正式灵矿池")

    def _load_beast_veins(self, rows: Sequence[Any]) -> None:
        for raw in rows:
            row = _mapping(raw, "炼器归引")
            _expect_fields(
                row,
                required={"兽宝池", "兽脉"},
                optional=set(),
                label="炼器归引",
            )
            pool = _text(row.get("兽宝池"), "兽宝池")
            vein = _text(row.get("兽脉"), f"{pool} 兽脉")
            if pool in self._beast_veins:
                raise ForgeError(f"兽宝池重复归引：{pool}")
            members = self._data.pool_members((pool,), "物品")
            if not members or any(self._items.item(value).category != "兽宝" for value in members):
                raise ForgeError(f"归引池不是纯兽宝池：{pool}")
            self._beast_veins[pool] = vein
        expected = {value.source_pool for value in self._items.items("兽宝")}
        if set(self._beast_veins) != expected:
            raise ForgeError("炼器归引没有完整覆盖正式兽宝池")

    def _load_methods(self, rows: Sequence[Any]) -> None:
        for raw in rows:
            row = _mapping(raw, "铸法")
            _expect_fields(
                row,
                required={"名称", "器阶", "铸势", "辅材"},
                optional=set(),
                label="铸法",
            )
            name = _text(row.get("名称"), "铸法名称")
            tier_name = _text(row.get("器阶"), f"铸法 {name} 器阶")
            tier = self._tiers.get(tier_name)
            if tier is None:
                raise ForgeError(f"铸法 {name} 引用未知器阶：{tier_name}")
            requirements = tuple(
                ForgeVeinRequirement(
                    vein=_text(value.get("铸脉"), f"铸法 {name} 铸脉"),
                    count=_positive_int(value.get("份数"), f"铸法 {name} 份数"),
                )
                for value in (
                    _strict_method_requirement(item, name)
                    for item in _sequence(row.get("辅材"), f"铸法 {name} 辅材")
                )
            )
            method = ForgeMethod(
                name=name,
                tier=tier_name,
                description=_text(row.get("铸势"), f"铸法 {name} 铸势"),
                requirements=requirements,
            )
            if name in self._methods or not requirements:
                raise ForgeError(f"铸法名称重复或没有辅材：{name}")
            if not tier.minimum_mineral_slots <= method.slot_count <= tier.maximum_mineral_slots:
                raise ForgeError(f"铸法 {name} 的矿材份数不属于{tier_name}")
            self._methods[name] = method

    def _load_laws(self) -> None:
        mechanism_ids = set(self._data.entities("机制"))
        law_names: set[str] = set()
        beast_veins = set(self._beast_veins.values())
        mineral_veins = {
            vein for values in self._mineral_veins.values() for vein in values
        }
        for identity, raw in self._data.entities("器律").items():
            _expect_fields(
                raw,
                required={"编号", "名称", "器阶", "铸法", "兽引", "能力"},
                optional=set(),
                label=f"器律 {identity}",
            )
            if str(raw.get("编号")) != identity:
                raise ForgeError(f"器律 {identity} 编号与索引不一致")
            tier_name = _text(raw.get("器阶"), f"器律 {identity} 器阶")
            tier = self._tiers.get(tier_name)
            if tier is None or tier.open_slots == 0:
                raise ForgeError(f"器律 {identity} 使用未知或未开孔器阶：{tier_name}")
            method_name = _text(raw.get("铸法"), f"器律 {identity} 铸法")
            method = self._methods.get(method_name)
            if method is None or method.tier != tier_name:
                raise ForgeError(f"器律 {identity} 的铸法与器阶不一致")
            unknown_mineral_veins = {
                value.vein for value in method.requirements
            } - mineral_veins
            if unknown_mineral_veins:
                raise ForgeError(f"器律 {identity} 的铸法引用未知铸脉")
            guide_veins = _strings(raw.get("兽引"), f"器律 {identity} 兽引", unique=False)
            if len(guide_veins) != tier.guide_count or set(guide_veins) - beast_veins:
                raise ForgeError(f"器律 {identity} 的兽引数量或兽脉不合法")
            name = _text(raw.get("名称"), f"器律 {identity} 名称")
            if name in law_names:
                raise ForgeError(f"器律名称重复：{name}")
            mechanisms = _validate_law_abilities(raw.get("能力"), identity)
            if not mechanisms or set(mechanisms) - mechanism_ids:
                raise ForgeError(f"器律 {identity} 没有机制或引用未知机制")
            if any(
                self._data.entity("机制", value)["节点"]["能力"] != "监听事件"
                for value in mechanisms
            ):
                raise ForgeError(f"器律 {identity} 只能引用监听型被动机制")
            self._laws[identity] = ForgeLawDefinition(
                identity=identity,
                name=name,
                tier=tier_name,
                forge_method=method_name,
                guide_veins=guide_veins,
                mechanism_ids=mechanisms,
            )
            law_names.add(name)

    def _validate_weapon(self, state: WeaponState) -> WeaponState:
        level = _positive_int(state.level, "本命武器等级")
        if not self._initial_level <= level <= self._maximum_level:
            raise ForgeError("本命武器等级超出规则范围")
        experience = _nonnegative_int(state.experience, "本命武器经验")
        if level == self._maximum_level and experience:
            raise ForgeError("满级本命武器不能保留升级经验")
        laws = tuple(state.laws)
        if len(laws) != self._slot_count:
            raise ForgeError(f"本命武器必须保存 {self._slot_count} 个器律孔")
        tier = self.tier_for_level(level)
        for index, law_id in enumerate(laws, start=1):
            if law_id is None:
                continue
            law = self.law(law_id)
            if index > tier.open_slots:
                raise ForgeError(f"未开放的器律孔 {index} 不能保存器律")
            if self._tier_order[law.tier] > self._tier_order[tier.name]:
                raise ForgeError(f"器律 {law_id} 超出当前本命武器器阶")
        return WeaponState(level=level, experience=experience, laws=laws)

    def _validate_guides(
        self,
        law: ForgeLawDefinition,
        tier: WeaponTier,
        guides: tuple[ForgeMaterial, ...],
    ) -> None:
        if len(guides) != tier.guide_count:
            raise ForgeError(f"{law.name}需要 {tier.guide_count} 件兽宝共同为引")
        identities = tuple(value.item_id for value in guides)
        if any(identities.count(value) > self._same_guide_limit for value in identities):
            raise ForgeError("同一件兽宝不能重复占据兽引位")
        actual_veins = []
        for guide in guides:
            item = self._items.item(guide.item_id)
            if item.category != "兽宝":
                raise ForgeError(f"兽引必须是兽宝：{guide.item_id}")
            self._require_grade(guide.grade, tier.minimum_guide_grade, "兽引")
            actual_veins.append(self._beast_veins[item.source_pool])
        if Counter(actual_veins) != Counter(law.guide_veins):
            raise ForgeError(
                f"兽引不能形成{law.name}：需要{'、'.join(law.guide_veins)}"
            )

    def _validate_auxiliaries(
        self,
        tier: WeaponTier,
        auxiliaries: tuple[ForgeMaterial, ...],
    ) -> None:
        identities = tuple(value.item_id for value in auxiliaries)
        if any(identities.count(value) > self._same_mineral_limit for value in identities):
            raise ForgeError("同一灵矿不能重复占据矿材位")
        for material in auxiliaries:
            item = self._items.item(material.item_id)
            if item.category != "灵矿":
                raise ForgeError(f"炼器辅材必须是灵矿：{material.item_id}")
            if item.source_pool not in self._mineral_veins:
                raise ForgeError(f"灵矿没有归脉：{material.item_id}")
            self._require_grade(material.grade, tier.minimum_mineral_grade, "矿材")

    def _allocate(
        self,
        required_slots: tuple[str, ...],
        materials: tuple[ForgeMaterial, ...],
        *,
        side_limit: int,
    ) -> tuple[ForgeAllocation, ...] | None:
        veins = tuple(
            self._mineral_veins[self._items.item(material.item_id).source_pool]
            for material in materials
        )

        def search(
            slot_index: int,
            unused: tuple[int, ...],
            side_used: int,
            allocations: tuple[ForgeAllocation, ...],
        ) -> tuple[ForgeAllocation, ...] | None:
            if slot_index == len(required_slots):
                if not unused:
                    return tuple(sorted(allocations, key=lambda value: value.material.item_id))
                return None
            required = required_slots[slot_index]
            direct = [index for index in unused if veins[index][0] == required]
            for group in itertools.combinations(direct, self._direct_material_count):
                result = search(
                    slot_index + 1,
                    tuple(value for value in unused if value not in group),
                    side_used,
                    allocations
                    + tuple(
                        ForgeAllocation(materials[index], required, DIRECT_MODE)
                        for index in group
                    ),
                )
                if result is not None:
                    return result
            if side_used >= side_limit:
                return None
            side = [index for index in unused if veins[index][1] == required]
            for group in itertools.combinations(side, self._side_material_count):
                result = search(
                    slot_index + 1,
                    tuple(value for value in unused if value not in group),
                    side_used + 1,
                    allocations
                    + tuple(
                        ForgeAllocation(materials[index], required, SIDE_MODE)
                        for index in group
                    ),
                )
                if result is not None:
                    return result
            return None

        return search(0, tuple(range(len(materials))), 0, ())

    def _validate_material(self, value: ForgeMaterial, label: str) -> ForgeMaterial:
        item_id = _text(value.item_id, f"{label}编号")
        grade = _grade(value.grade, self._grades, f"{label}品级")
        self._items.item(item_id)
        return ForgeMaterial(item_id=item_id, grade=grade)

    def _require_grade(self, actual: str, minimum: str, label: str) -> None:
        if self._grades[actual] < self._grades[minimum]:
            raise ForgeError(f"{label}品级不足：需要 {minimum}，实际 {actual}")

    def _require_initialized(self) -> None:
        if not self._laws:
            raise RuntimeError("炼器微服务尚未初始化")


def _validate_law_abilities(value: Any, identity: str) -> tuple[str, ...]:
    abilities = _sequence(value, f"器律 {identity} 能力")
    if not abilities:
        raise ForgeError(f"器律 {identity} 至少需要一个被动技能")
    mechanisms: list[str] = []
    for index, raw in enumerate(abilities, start=1):
        ability = _mapping(raw, f"器律 {identity} 能力 {index}")
        _expect_fields(
            ability,
            required={"能力", "名称", "结算顺序", "效果"},
            optional=set(),
            label=f"器律 {identity} 能力 {index}",
        )
        if _text(ability.get("能力"), f"器律 {identity} 能力类型") != "被动技能":
            raise ForgeError(f"器律 {identity} 只能装配被动技能")
        _text(ability.get("名称"), f"器律 {identity} 能力名称")
        _positive_int(ability.get("结算顺序"), f"器律 {identity} 结算顺序")
        effects = _sequence(ability.get("效果"), f"器律 {identity} 被动效果")
        if not effects:
            raise ForgeError(f"器律 {identity} 被动技能必须引用机制")
        for raw_effect in effects:
            effect = _mapping(raw_effect, f"器律 {identity} 被动效果")
            _expect_fields(
                effect,
                required={"能力", "机制"},
                optional=set(),
                label=f"器律 {identity} 被动效果",
            )
            if _text(effect.get("能力"), f"器律 {identity} 被动效果类型") != "引用被动机制":
                raise ForgeError(f"器律 {identity} 只能引用被动机制")
            mechanisms.append(_text(effect.get("机制"), f"器律 {identity} 机制编号"))
    return tuple(mechanisms)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ForgeError(f"{label}必须是对象")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ForgeError(f"{label}必须是列表")
    return value


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ForgeError(f"{label}不能为空")
    return result


def _strings(value: Any, label: str, *, unique: bool = True) -> tuple[str, ...]:
    result = tuple(_text(item, label) for item in _sequence(value, label))
    if unique and len(result) != len(set(result)):
        raise ForgeError(f"{label}不能重复")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ForgeError(f"{label}必须是非负整数")
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result < 1:
        raise ForgeError(f"{label}必须大于 0")
    return result


def _nonnegative_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ForgeError(f"{label}必须是非负数值")
    return float(value)


def _positive_number(value: Any, label: str) -> float:
    result = _nonnegative_number(value, label)
    if result <= 0:
        raise ForgeError(f"{label}必须大于 0")
    return result


def _validate_experience_late(value: Any, label: str) -> Mapping[str, Any]:
    rule = _mapping(value, label)
    _expect_fields(
        rule,
        required={
            "起始等级",
            "跨度",
            "中段系数",
            "中段幂次",
            "高段系数",
            "高段幂次",
            "终段系数",
            "终段幂次",
        },
        optional=set(),
        label=label,
    )
    _positive_int(rule.get("起始等级"), f"{label}起始等级")
    _positive_int(rule.get("跨度"), f"{label}跨度")
    for section in ("中段", "高段", "终段"):
        _nonnegative_number(rule.get(f"{section}系数"), f"{label}{section}系数")
        _positive_number(rule.get(f"{section}幂次"), f"{label}{section}幂次")
    return rule


def _grade(value: Any, grades: Mapping[str, int], label: str) -> str:
    result = _text(value, label)
    if result not in grades:
        raise ForgeError(f"{label}不存在：{result}")
    return result


def _range_pair(
    value: Any,
    label: str,
    *,
    allow_zero: bool = False,
) -> tuple[int, int]:
    values = _sequence(value, label)
    if len(values) != 2:
        raise ForgeError(f"{label}必须包含最小值和最大值")
    parser = _nonnegative_int if allow_zero else _positive_int
    lower = parser(values[0], f"{label}最小值")
    upper = parser(values[1], f"{label}最大值")
    if upper < lower:
        raise ForgeError(f"{label}最大值不能小于最小值")
    return lower, upper


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
        raise ForgeError(f"{label}缺少字段：{'、'.join(sorted(missing))}")
    if unknown:
        raise ForgeError(f"{label}存在未知字段：{'、'.join(sorted(unknown))}")


def _strict_method_requirement(value: Any, name: str) -> Mapping[str, Any]:
    row = _mapping(value, f"铸法 {name} 辅材")
    _expect_fields(
        row,
        required={"铸脉", "份数"},
        optional=set(),
        label=f"铸法 {name} 辅材",
    )
    return row


__all__ = ["DIRECT_MODE", "SIDE_MODE", "ForgeService"]
