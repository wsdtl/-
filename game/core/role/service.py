"""把角色、成长和阶梯 JSON 组装为稳定角色档案。"""

from __future__ import annotations

import random
import secrets
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from game.core.data import JsonDataService
from game.core.item import ItemService

from .contracts import (
    RoleBuildSlot,
    RoleError,
    RoleItemStack,
    RoleProfile,
    RoleStatus,
)

BUILD_SECTIONS = ("功法", "附魔", "宝石")


class RoleService:
    """解释人物、道侣和敌人共同角色结构，不保存角色实例。"""

    def __init__(self, data: JsonDataService, items: ItemService) -> None:
        self._data = data
        self._items = items
        self._attribute_defaults: dict[str, float] = {}
        self._growth_rules: dict[str, Mapping[str, Any]] = {}
        self._role_rules: dict[str, Mapping[str, Any]] = {}
        self._player_rule: Mapping[str, Any] | None = None
        self._companion_rule: Mapping[str, Any] | None = None
        self._weapon_rules: dict[str, Mapping[str, Any]] = {}
        self._companions: Mapping[str, Mapping[str, Any]] = {}
        self._enemies: Mapping[str, Mapping[str, Any]] = {}

    def initialize(self) -> RoleStatus:
        if self._player_rule is not None:
            raise RuntimeError("角色微服务已经初始化")
        if not self._items.status().initialized:
            raise RuntimeError("物品微服务必须先于角色微服务启动")
        self._load_attribute_defaults()
        rules = self._data.dataset("角色规则")
        self._growth_rules = {
            name: self._validate_growth_rule(name, rules[name])
            for name in ("修士修炼", "灵兽修炼")
        }
        self._weapon_rules = {
            "本命武器": self._validate_weapon_rule(rules.get("本命武器"))
        }
        self._player_rule = self._validate_player_rule(rules.get("人物"))
        self._companion_rule = self._validate_companion_rule(rules.get("道侣"))
        self._role_rules = {
            "敌方修士": self._validate_tier_rule("敌方修士", rules.get("敌方修士")),
            "灵兽": self._validate_tier_rule("灵兽", rules.get("灵兽")),
        }
        self._companions = self._data.entities("道侣")
        self._enemies = self._data.entities("敌人")
        self._validate_companions()
        self._validate_enemies()
        return self.status()

    def status(self) -> RoleStatus:
        return RoleStatus(
            initialized=self._player_rule is not None,
            companion_count=len(self._companions),
            enemy_count=len(self._enemies),
            growth_rule_count=len(self._growth_rules),
        )

    def player(self) -> RoleProfile:
        rule = self._require_player_rule()
        level = _positive_int(rule.get("等级"), "人物等级")
        attributes = self._attributes(
            self._growth_rules[_text(rule.get("成长规则"), "人物成长规则")],
            level,
            _mapping(rule.get("属性覆盖"), "人物属性覆盖"),
        )
        resources = self._resources(rule.get("资源"), attributes)
        inventory = tuple(
            RoleItemStack(
                identity=_text(row.get("编号"), "初始物品编号"),
                quantity=_positive_int(row.get("数量"), "初始物品数量"),
            )
            for row in (
                _mapping(raw, "初始物品")
                for raw in _sequence(rule.get("物品"), "初始物品")
            )
        )
        weapon = self._weapon_rules[_text(rule.get("本命武器规则"), "本命武器规则")]
        return RoleProfile(
            identity="人物",
            name="人物",
            kind=_text(rule.get("角色类型"), "人物角色类型"),
            level=level,
            qualification=None,
            attributes=MappingProxyType(attributes),
            resources=MappingProxyType(resources),
            weapon_attack=self._weapon_attack(weapon, level),
            build_slots=self._build_slots(rule.get("构筑位"), full_pool=True),
            inventory=inventory,
            auto_medicine=_boolean(rule.get("自动用药"), "人物自动用药"),
        )

    def companion(
        self,
        identity: str,
        *,
        level: int | None = None,
        qualification: int | None = None,
        seed: int | None = None,
    ) -> RoleProfile:
        rule = self._require_companion_rule()
        key = _text(identity, "道侣编号")
        try:
            entity = self._companions[key]
        except KeyError as exc:
            raise RoleError(f"道侣不存在：{key}") from exc
        actual_level = level or _positive_int(entity.get("等级"), f"道侣 {key} 等级")
        qualification_range = _range_pair(
            entity.get("资质范围"), f"道侣 {key} 资质范围", minimum=1
        )
        rng = random.Random(_seed(seed))
        actual_qualification = qualification or rng.randint(*qualification_range)
        if not qualification_range[0] <= actual_qualification <= qualification_range[1]:
            raise RoleError(f"道侣 {key} 资质超出范围")
        multiplier = self._qualification_multiplier(
            actual_qualification,
            qualification_range,
            _mapping(rule.get("资质成长修正"), "资质成长修正"),
        )
        attributes = self._attributes(
            self._growth_rules[_text(rule.get("成长规则"), "道侣成长规则")],
            actual_level,
            _mapping(entity.get("属性覆盖"), f"道侣 {key} 属性覆盖"),
            growth_multiplier=multiplier,
        )
        self._apply_fluctuation(attributes, entity.get("实力波动"), rng, f"道侣 {key}")
        weapon_rule = self._weapon_rules[
            _text(rule.get("本命武器规则"), "道侣本命武器规则")
        ]
        pools = {
            section: (_text(entity.get(f"{section}池"), f"道侣 {key} {section}池"),)
            for section in BUILD_SECTIONS
        }
        return RoleProfile(
            identity=key,
            name=_text(entity.get("名称"), f"道侣 {key} 名称"),
            kind=_text(rule.get("角色类型"), "道侣角色类型"),
            level=actual_level,
            qualification=actual_qualification,
            attributes=MappingProxyType(attributes),
            resources=MappingProxyType(self._default_resources(attributes)),
            weapon_attack=self._weapon_attack(weapon_rule, actual_level),
            build_slots=self._build_slots(rule.get("构筑位"), pools=pools),
        )

    def enemy(
        self,
        identity: str,
        *,
        level: int | None = None,
        seed: int | None = None,
    ) -> RoleProfile:
        self._require_initialized()
        key = _text(identity, "敌人名称")
        try:
            entity = self._enemies[key]
        except KeyError as exc:
            raise RoleError(f"敌人不存在：{key}") from exc
        rng = random.Random(_seed(seed))
        level_range = _range_pair(entity.get("等级"), f"敌人 {key} 等级", minimum=1)
        actual_level = level or rng.randint(*level_range)
        if not level_range[0] <= actual_level <= level_range[1]:
            raise RoleError(f"敌人 {key} 等级超出定义范围")
        rule_name = _text(entity.get("角色规则"), f"敌人 {key} 角色规则")
        role_rule = self._role_rules[rule_name]
        growth = self._growth_rules[_text(role_rule.get("成长规则"), "敌人成长规则")]
        attributes = self._attributes(
            growth,
            actual_level,
            _mapping(entity.get("属性覆盖"), f"敌人 {key} 属性覆盖"),
            growth_correction=_mapping(
                entity.get("每级成长修正", {}), f"敌人 {key} 每级成长修正"
            ),
        )
        tier = self._tier_for(role_rule, actual_level)
        attributes["速度"] += _number(tier.get("每级速度"), "每级速度") * (
            actual_level - 1
        )
        attributes["控制抵抗率"] += _number(
            tier.get("固定控制抵抗率"), "固定控制抵抗率"
        )
        attributes["韧性"] += _number(tier.get("固定韧性"), "固定韧性")
        self._apply_fluctuation(attributes, entity.get("实力波动"), rng, f"敌人 {key}")
        pools = {
            section: (_text(tier.get(f"{section}池"), f"敌人 {key} {section}池"),)
            for section in BUILD_SECTIONS
        }
        weapon = entity.get("本命武器")
        weapon_attack = (
            _nonnegative_number(
                _mapping(weapon, f"敌人 {key} 本命武器").get("攻击"),
                f"敌人 {key} 本命武器攻击",
            )
            if weapon is not None
            else 0.0
        )
        return RoleProfile(
            identity=key,
            name=key,
            kind=_text(role_rule.get("角色类型"), f"敌人 {key} 角色类型"),
            level=actual_level,
            qualification=None,
            attributes=MappingProxyType(attributes),
            resources=MappingProxyType(self._default_resources(attributes)),
            weapon_attack=weapon_attack,
            build_slots=self._build_slots(tier.get("构筑位"), pools=pools),
        )

    def _load_attribute_defaults(self) -> None:
        definitions = self._data.dataset("战斗定义")
        attributes = _mapping(definitions.get("属性"), "战斗属性定义")
        for name, raw in attributes.items():
            definition = _mapping(raw, f"属性 {name}")
            self._attribute_defaults[str(name)] = _number(
                definition.get("默认值"), f"属性 {name} 默认值"
            )

    def _validate_growth_rule(self, name: str, value: Any) -> Mapping[str, Any]:
        rule = _mapping(value, f"成长规则 {name}")
        _strict_fields(
            rule,
            {"属性基准", "等级上限", "突破间隔", "属性成长", "经验"},
            f"成长规则 {name}",
            optional={"初始属性"},
        )
        if _text(rule.get("属性基准"), f"成长规则 {name} 属性基准") != "定义默认值":
            raise RoleError(f"成长规则 {name} 必须使用定义默认值")
        _positive_int(rule.get("等级上限"), f"成长规则 {name} 等级上限")
        _positive_int(rule.get("突破间隔"), f"成长规则 {name} 突破间隔")
        growth = _mapping(rule.get("属性成长"), f"成长规则 {name} 属性成长")
        _strict_fields(growth, {"起始等级", "每级"}, f"成长规则 {name} 属性成长")
        _positive_int(growth.get("起始等级"), f"成长规则 {name} 起始等级")
        self._validate_attributes(growth.get("每级"), f"成长规则 {name} 每级成长")
        self._validate_attributes(rule.get("初始属性", {}), f"成长规则 {name} 初始属性")
        experience = _mapping(rule.get("经验"), f"成长规则 {name} 经验")
        _strict_fields(experience, {"基础", "等级平方系数"}, f"成长规则 {name} 经验")
        _positive_int(experience.get("基础"), f"成长规则 {name} 经验基础")
        _positive_int(experience.get("等级平方系数"), f"成长规则 {name} 经验系数")
        return rule

    def _validate_weapon_rule(self, value: Any) -> Mapping[str, Any]:
        rule = _mapping(value, "本命武器规则")
        _strict_fields(
            rule,
            {"初始等级", "等级上限", "基础攻击", "每级攻击", "经验"},
            "本命武器规则",
        )
        for field in ("初始等级", "等级上限"):
            _positive_int(rule.get(field), f"本命武器 {field}")
        for field in ("基础攻击", "每级攻击"):
            _nonnegative_number(rule.get(field), f"本命武器 {field}")
        experience = _mapping(rule.get("经验"), "本命武器经验")
        _strict_fields(experience, {"基础", "等级平方系数"}, "本命武器经验")
        return rule

    def _validate_player_rule(self, value: Any) -> Mapping[str, Any]:
        rule = _mapping(value, "人物规则")
        _strict_fields(
            rule,
            {
                "角色类型",
                "成长规则",
                "本命武器规则",
                "构筑位",
                "等级",
                "经验",
                "灵石",
                "属性覆盖",
                "资源",
                "状态",
                "自动用药",
                "物品",
            },
            "人物规则",
        )
        self._require_growth_reference(rule.get("成长规则"), "人物")
        self._require_weapon_reference(rule.get("本命武器规则"), "人物")
        self._validate_build_slots(rule.get("构筑位"), "人物构筑位")
        self._validate_attributes(rule.get("属性覆盖"), "人物属性覆盖")
        if not isinstance(rule.get("状态"), Sequence):
            raise RoleError("人物状态必须是列表")
        seen: set[str] = set()
        for raw in _sequence(rule.get("物品"), "人物初始物品"):
            row = _mapping(raw, "人物初始物品")
            _strict_fields(row, {"编号", "数量"}, "人物初始物品")
            identity = _text(row.get("编号"), "人物初始物品编号")
            self._items.item(identity)
            if identity in seen:
                raise RoleError(f"人物初始物品重复：{identity}")
            seen.add(identity)
            _positive_int(row.get("数量"), "人物初始物品数量")
        return rule

    def _validate_companion_rule(self, value: Any) -> Mapping[str, Any]:
        rule = _mapping(value, "道侣规则")
        _strict_fields(
            rule,
            {
                "角色类型",
                "成长规则",
                "本命武器规则",
                "好感上限",
                "赠礼每件好感",
                "构筑位",
                "资质成长修正",
            },
            "道侣规则",
        )
        self._require_growth_reference(rule.get("成长规则"), "道侣")
        self._require_weapon_reference(rule.get("本命武器规则"), "道侣")
        self._validate_build_slots(rule.get("构筑位"), "道侣构筑位")
        correction = _mapping(rule.get("资质成长修正"), "资质成长修正")
        _strict_fields(
            correction,
            {"作用", "方式", "最低倍率", "最高倍率", "范围同值倍率"},
            "资质成长修正",
        )
        return rule

    def _validate_tier_rule(self, name: str, value: Any) -> Mapping[str, Any]:
        rule = _mapping(value, f"角色规则 {name}")
        _strict_fields(rule, {"角色类型", "成长规则", "阶梯"}, f"角色规则 {name}")
        self._require_growth_reference(rule.get("成长规则"), name)
        previous_end = 0
        tier_names: set[str] = set()
        for raw in _sequence(rule.get("阶梯"), f"角色规则 {name} 阶梯"):
            tier = _mapping(raw, f"角色规则 {name} 阶梯")
            _strict_fields(
                tier,
                {
                    "阶梯",
                    "等级范围",
                    "构筑位",
                    "功法池",
                    "附魔池",
                    "宝石池",
                    "每级速度",
                    "固定控制抵抗率",
                    "固定韧性",
                },
                f"角色规则 {name} 阶梯",
            )
            tier_name = _text(tier.get("阶梯"), f"角色规则 {name} 阶梯名称")
            lower, upper = _range_pair(tier.get("等级范围"), f"{name} {tier_name} 等级", minimum=1)
            if tier_name in tier_names or lower != previous_end + 1:
                raise RoleError(f"角色规则 {name} 阶梯名称或等级范围不连续")
            previous_end = upper
            tier_names.add(tier_name)
            self._validate_build_slots(tier.get("构筑位"), f"{name} {tier_name} 构筑位")
            for section in BUILD_SECTIONS:
                self._data.pool_members((_text(tier.get(f"{section}池"), f"{section}池"),), section)
        if previous_end != _positive_int(
            self._growth_rules[_text(rule.get("成长规则"), name)].get("等级上限"),
            f"{name} 等级上限",
        ):
            raise RoleError(f"角色规则 {name} 阶梯没有覆盖完整等级")
        return rule

    def _validate_companions(self) -> None:
        names: set[str] = set()
        for identity, entity in self._companions.items():
            _strict_fields(
                entity,
                {
                    "编号",
                    "名称",
                    "功法池",
                    "附魔池",
                    "宝石池",
                    "身份",
                    "说明",
                    "结交",
                    "等级",
                    "实力波动",
                    "属性覆盖",
                    "资质范围",
                },
                f"道侣 {identity}",
            )
            if str(entity.get("编号")) != identity:
                raise RoleError(f"道侣 {identity} 编号与索引不一致")
            name = _text(entity.get("名称"), f"道侣 {identity} 名称")
            if name in names:
                raise RoleError(f"道侣名称重复：{name}")
            names.add(name)
            for section in BUILD_SECTIONS:
                self._data.pool_members(
                    (_text(entity.get(f"{section}池"), f"道侣 {identity} {section}池"),),
                    section,
                )
            self._validate_attributes(entity.get("属性覆盖"), f"道侣 {identity} 属性覆盖")
            self._validate_fluctuation(entity.get("实力波动"), f"道侣 {identity} 实力波动")
            _range_pair(entity.get("资质范围"), f"道侣 {identity} 资质范围", minimum=1)
            relation = _mapping(entity.get("结交"), f"道侣 {identity} 结交")
            _strict_fields(
                relation,
                {"灵植池", "圆满回礼", "入队话语", "离队话语"},
                f"道侣 {identity} 结交",
            )
            gift = _mapping(relation.get("圆满回礼"), f"道侣 {identity} 圆满回礼")
            _strict_fields(gift, {"编号", "品级", "数量"}, f"道侣 {identity} 圆满回礼")
            self._items.item(_text(gift.get("编号"), f"道侣 {identity} 回礼编号"))

    def _validate_enemies(self) -> None:
        for identity, entity in self._enemies.items():
            role_name = _text(entity.get("角色规则"), f"敌人 {identity} 角色规则")
            if role_name not in self._role_rules:
                raise RoleError(f"敌人 {identity} 使用未知角色规则：{role_name}")
            required = {
                "角色规则",
                "说明",
                "权重",
                "等级",
                "实力波动",
                "属性覆盖",
                "掉落",
                "交锋所得",
            }
            optional = {"本命武器", "每级成长修正"}
            _strict_fields(entity, required, f"敌人 {identity}", optional=optional)
            if role_name == "敌方修士" and "本命武器" not in entity:
                raise RoleError(f"敌方修士 {identity} 缺少本命武器")
            if role_name == "灵兽" and "每级成长修正" not in entity:
                raise RoleError(f"灵兽 {identity} 缺少每级成长修正")
            self._validate_attributes(entity.get("属性覆盖"), f"敌人 {identity} 属性覆盖")
            self._validate_attributes(
                entity.get("每级成长修正", {}), f"敌人 {identity} 每级成长修正"
            )
            self._validate_fluctuation(entity.get("实力波动"), f"敌人 {identity} 实力波动")
            _range_pair(entity.get("等级"), f"敌人 {identity} 等级", minimum=1)
            drop = _mapping(entity.get("掉落"), f"敌人 {identity} 掉落")
            _strict_fields(drop, {"灵石", "物品池"}, f"敌人 {identity} 掉落")
            _range_pair(drop.get("灵石"), f"敌人 {identity} 掉落灵石", minimum=0)
            encounter = _mapping(entity.get("交锋所得"), f"敌人 {identity} 交锋所得")
            _strict_fields(encounter, {"本命武器经验"}, f"敌人 {identity} 交锋所得")
            _range_pair(
                encounter.get("本命武器经验"),
                f"敌人 {identity} 本命武器经验",
                minimum=0,
            )
            weapon = entity.get("本命武器")
            if weapon is not None:
                weapon_value = _mapping(weapon, f"敌人 {identity} 本命武器")
                _strict_fields(weapon_value, {"名称", "攻击"}, f"敌人 {identity} 本命武器")

    def _attributes(
        self,
        growth_rule: Mapping[str, Any],
        level: int,
        overrides: Mapping[str, Any],
        *,
        growth_multiplier: float = 1.0,
        growth_correction: Mapping[str, Any] | None = None,
    ) -> dict[str, float]:
        level_cap = _positive_int(growth_rule.get("等级上限"), "成长等级上限")
        if not 1 <= level <= level_cap:
            raise RoleError(f"角色等级必须在 1 至 {level_cap} 之间")
        result = dict(self._attribute_defaults)
        result.update(
            {
                str(name): _number(value, f"初始属性 {name}")
                for name, value in _mapping(
                    growth_rule.get("初始属性", {}), "成长初始属性"
                ).items()
            }
        )
        result.update(
            {
                str(name): _number(value, f"属性覆盖 {name}")
                for name, value in overrides.items()
            }
        )
        growth = _mapping(growth_rule.get("属性成长"), "属性成长")
        start = _positive_int(growth.get("起始等级"), "成长起始等级")
        increments = max(0, level - start + 1)
        corrections = growth_correction or {}
        for name, value in _mapping(growth.get("每级"), "每级成长").items():
            amount = _number(value, f"每级成长 {name}") + _number(
                corrections.get(name, 0), f"每级成长修正 {name}"
            )
            result[str(name)] += amount * growth_multiplier * increments
        return {name: round(value, 10) for name, value in result.items()}

    def _apply_fluctuation(
        self,
        attributes: dict[str, float],
        raw: Any,
        rng: random.Random,
        label: str,
    ) -> None:
        value = _mapping(raw, f"{label} 实力波动")
        names = _strings(value.get("属性"), f"{label} 波动属性")
        lower, upper = _range_pair(value.get("倍率"), f"{label} 波动倍率", minimum=1)
        for name in names:
            attributes[name] = round(attributes[name] * rng.randint(lower, upper) / 100, 10)

    @staticmethod
    def _qualification_multiplier(
        qualification: int,
        bounds: tuple[int, int],
        rule: Mapping[str, Any],
    ) -> float:
        if bounds[0] == bounds[1]:
            return _positive_number(rule.get("范围同值倍率"), "范围同值倍率")
        minimum = _positive_number(rule.get("最低倍率"), "资质最低倍率")
        maximum = _positive_number(rule.get("最高倍率"), "资质最高倍率")
        ratio = (qualification - bounds[0]) / (bounds[1] - bounds[0])
        return minimum + (maximum - minimum) * ratio

    def _build_slots(
        self,
        raw: Any,
        *,
        pools: Mapping[str, tuple[str, ...]] | None = None,
        full_pool: bool = False,
    ) -> tuple[RoleBuildSlot, ...]:
        values = _mapping(raw, "构筑位")
        return tuple(
            RoleBuildSlot(
                section=section,
                count=_nonnegative_int(values.get(section), f"{section}构筑位"),
                file_ids=() if pools is None else pools[section],
                full_pool=full_pool,
            )
            for section in BUILD_SECTIONS
        )

    @staticmethod
    def _tier_for(rule: Mapping[str, Any], level: int) -> Mapping[str, Any]:
        for raw in _sequence(rule.get("阶梯"), "角色阶梯"):
            tier = _mapping(raw, "角色阶梯")
            lower, upper = _range_pair(tier.get("等级范围"), "角色阶梯等级", minimum=1)
            if lower <= level <= upper:
                return tier
        raise RoleError(f"等级 {level} 没有对应角色阶梯")

    @staticmethod
    def _weapon_attack(rule: Mapping[str, Any], level: int) -> float:
        initial = _positive_int(rule.get("初始等级"), "本命武器初始等级")
        return _nonnegative_number(rule.get("基础攻击"), "本命武器基础攻击") + max(
            0, level - initial
        ) * _nonnegative_number(rule.get("每级攻击"), "本命武器每级攻击")

    @staticmethod
    def _resources(raw: Any, attributes: Mapping[str, float]) -> dict[str, float]:
        values = _mapping(raw, "人物资源")
        result: dict[str, float] = {}
        limits = {"血气": "血气上限", "精神": "精神上限", "护盾": "护盾上限"}
        for name, value in values.items():
            result[str(name)] = (
                attributes[limits[str(name)]]
                if value == "上限"
                else _nonnegative_number(value, f"资源 {name}")
            )
        return result

    @staticmethod
    def _default_resources(attributes: Mapping[str, float]) -> dict[str, float]:
        return {
            "血气": attributes["血气上限"],
            "精神": attributes["精神上限"],
            "护盾": 0.0,
        }

    def _validate_attributes(self, raw: Any, label: str) -> None:
        values = _mapping(raw, label)
        unknown = set(values) - set(self._attribute_defaults)
        if unknown:
            raise RoleError(f"{label}引用未知属性：{'、'.join(sorted(unknown))}")
        for name, value in values.items():
            _number(value, f"{label}.{name}")

    def _validate_fluctuation(self, raw: Any, label: str) -> None:
        value = _mapping(raw, label)
        _strict_fields(value, {"属性", "倍率"}, label)
        attributes = _strings(value.get("属性"), f"{label}.属性")
        unknown = set(attributes) - set(self._attribute_defaults)
        if unknown:
            raise RoleError(f"{label}引用未知属性：{'、'.join(sorted(unknown))}")
        _range_pair(value.get("倍率"), f"{label}.倍率", minimum=1)

    @staticmethod
    def _validate_build_slots(raw: Any, label: str) -> None:
        values = _mapping(raw, label)
        _strict_fields(values, set(BUILD_SECTIONS), label)
        for section in BUILD_SECTIONS:
            _nonnegative_int(values.get(section), f"{label}.{section}")

    def _require_growth_reference(self, value: Any, label: str) -> None:
        name = _text(value, f"{label}成长规则")
        if name not in self._growth_rules:
            raise RoleError(f"{label}引用未知成长规则：{name}")

    def _require_weapon_reference(self, value: Any, label: str) -> None:
        name = _text(value, f"{label}本命武器规则")
        if name not in self._weapon_rules:
            raise RoleError(f"{label}引用未知本命武器规则：{name}")

    def _require_player_rule(self) -> Mapping[str, Any]:
        self._require_initialized()
        assert self._player_rule is not None
        return self._player_rule

    def _require_companion_rule(self) -> Mapping[str, Any]:
        self._require_initialized()
        assert self._companion_rule is not None
        return self._companion_rule

    def _require_initialized(self) -> None:
        if self._player_rule is None:
            raise RuntimeError("角色微服务尚未初始化")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RoleError(f"{label}必须是对象")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RoleError(f"{label}必须是列表")
    return value


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise RoleError(f"{label}不能为空")
    return result


def _strings(value: Any, label: str) -> tuple[str, ...]:
    result = tuple(_text(item, label) for item in _sequence(value, label))
    if len(result) != len(set(result)):
        raise RoleError(f"{label}不能重复")
    return result


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoleError(f"{label}必须是数字")
    return float(value)


def _nonnegative_number(value: Any, label: str) -> float:
    result = _number(value, label)
    if result < 0:
        raise RoleError(f"{label}必须是非负数")
    return result


def _positive_number(value: Any, label: str) -> float:
    result = _number(value, label)
    if result <= 0:
        raise RoleError(f"{label}必须大于零")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RoleError(f"{label}必须是非负整数")
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result < 1:
        raise RoleError(f"{label}必须是正整数")
    return result


def _range_pair(value: Any, label: str, *, minimum: int) -> tuple[int, int]:
    values = _sequence(value, label)
    if len(values) != 2:
        raise RoleError(f"{label}必须包含两个整数")
    lower, upper = values
    if (
        isinstance(lower, bool)
        or isinstance(upper, bool)
        or not isinstance(lower, int)
        or not isinstance(upper, int)
        or lower < minimum
        or upper < lower
    ):
        raise RoleError(f"{label}范围无效")
    return lower, upper


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise RoleError(f"{label}必须是布尔值")
    return value


def _seed(value: int | None) -> int:
    if value is None:
        return secrets.randbits(64)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RoleError("角色随机种子必须是整数")
    return value


def _strict_fields(
    value: Mapping[str, Any],
    required: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> None:
    optional_fields = optional or set()
    unknown = set(value) - required - optional_fields
    missing = required - set(value)
    if unknown or missing:
        details = []
        if unknown:
            details.append("未知字段 " + "、".join(sorted(unknown)))
        if missing:
            details.append("缺少字段 " + "、".join(sorted(missing)))
        raise RoleError(f"{label}字段不完整：{'；'.join(details)}")


__all__ = ["RoleService"]
