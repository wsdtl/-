"""运行期中文配置的统一加载与跨文件校验。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from game.core import JsonDataError, JsonDataReader, rarity_weighted_choice
from game.rules.battle.catalog import BattleReportCatalog
from game.rules.battle.executors import EXECUTOR_CATEGORIES
from game.rules.battle.schema import RuleSchemaError, RuleSchemaValidator


PLAYER_FILE = "rules/人物/人物.json"
ACTIVITIES_FILE = "rules/修炼/修炼.json"
GRADES_FILE = "rules/品级/品级-通用.json"
ATTRIBUTES_FILE = "rules/战斗/属性.json"
RESOURCES_FILE = "rules/战斗/资源.json"
COMBAT_FLOW_FILE = "rules/战斗/流程.json"
ATOMIC_ABILITIES_FILE = "rules/战斗/原子能力.json"
BATTLE_REPORT_FILE = "rules/战斗/战报.json"
COMBAT_CONTENT_FILE = "content/战斗机制"
MECHANISMS_FILE = COMBAT_CONTENT_FILE
AFFIXES_FILE = COMBAT_CONTENT_FILE
ITEMS_FILE = "content/物品"
TECHNIQUES_FILE = f"{ITEMS_FILE}/功法"
ENCHANTMENTS_FILE = f"{ITEMS_FILE}/附魔技能书"
GEMS_FILE = f"{ITEMS_FILE}/宝石"
WEAPON_AUGMENTS_FILE = ITEMS_FILE
DIRECTIONS_FILE = "content/角色方向"
PARTNER_NPCS_FILE = "content/角色/伙伴修士"
HOSTILE_CULTIVATORS_FILE = "content/敌人/修士"
BEASTS_FILE = "content/敌人/灵兽"
NPCS_FILE = PARTNER_NPCS_FILE
ENEMIES_FILE = f"{HOSTILE_CULTIVATORS_FILE} 与 {BEASTS_FILE}"
WORLD_FILE = "content/世界/青岚山境.json"


class GameContentError(ValueError):
    """运行配置缺字段、引用错误或使用了未知战斗能力。"""


@dataclass(frozen=True)
class GameContent:
    player: dict[str, Any]
    activities: dict[str, Any]
    grades: dict[str, Any]
    combat: dict[str, Any]
    battle_report: BattleReportCatalog
    techniques: dict[str, Any]
    items: dict[str, Any]
    weapon_augments: dict[str, Any]
    directions: dict[str, Any]
    npcs: dict[str, Any]
    enemies: dict[str, Any]
    world: dict[str, Any]

    @classmethod
    def load(cls, reader: JsonDataReader) -> "GameContent":
        try:
            reader.validate_unique_filenames()
        except JsonDataError as exc:
            raise GameContentError(str(exc)) from exc
        attributes = _read_versioned(reader, ATTRIBUTES_FILE)
        resources = _read_versioned(reader, RESOURCES_FILE)
        flow = _read_versioned(reader, COMBAT_FLOW_FILE)
        abilities = _read_versioned(reader, ATOMIC_ABILITIES_FILE)
        combat_content = _read_multi_section_catalog(
            reader,
            directory=COMBAT_CONTENT_FILE,
            sections=("机制", "词条"),
        )
        mechanisms = {"版本": "目录展开", "机制": combat_content["机制"]}
        affixes = {"版本": "目录展开", "词条": combat_content["词条"]}
        battle_report = _read_versioned(reader, BATTLE_REPORT_FILE)
        try:
            battle_report_catalog = BattleReportCatalog.from_mapping(battle_report)
        except ValueError as exc:
            raise GameContentError(f"数据文件有问题：{BATTLE_REPORT_FILE}：{exc}") from exc

        enchantments = _read_multi_section_catalog(
            reader,
            directory=ENCHANTMENTS_FILE,
            sections=("附魔",),
        )
        gems = _read_multi_section_catalog(
            reader,
            directory=GEMS_FILE,
            sections=("宝石",),
        )
        weapon_augments = {
            "版本": "目录展开",
            "附魔": enchantments["附魔"],
            "宝石": gems["宝石"],
            "分组": {
                "附魔": enchantments["分组"]["附魔"],
                "宝石": gems["分组"]["宝石"],
            },
        }
        items = _read_item_catalog(reader, weapon_augments)

        content = cls(
            player=_read_versioned(reader, PLAYER_FILE),
            activities=_read_versioned(reader, ACTIVITIES_FILE),
            grades=_read_versioned(reader, GRADES_FILE),
            combat={
                "版本": "晓楠修仙.战斗组合.v1",
                "属性": _require_object(attributes, "属性", ATTRIBUTES_FILE),
                "人物必需属性": attributes.get("人物必需属性", []),
                "参战者必需属性": attributes.get("参战者必需属性", []),
                "资源": _require_object(resources, "资源", RESOURCES_FILE),
                "伤害规则": _require_object(flow, "伤害规则", COMBAT_FLOW_FILE),
                "行动规则": _require_object(flow, "行动规则", COMBAT_FLOW_FILE),
                "事件": flow.get("事件"),
                "原子能力": _require_object(abilities, "原子能力", ATOMIC_ABILITIES_FILE),
                "机制": _require_object(mechanisms, "机制", MECHANISMS_FILE),
                "词条": _require_object(affixes, "词条", AFFIXES_FILE),
            },
            battle_report=battle_report_catalog,
            techniques=_read_technique_catalog(reader),
            items=items,
            weapon_augments=weapon_augments,
            directions=_read_multi_section_catalog(
                reader,
                directory=DIRECTIONS_FILE,
                sections=("方向",),
            ),
            npcs=_read_grouped_catalog(
                reader,
                directory=PARTNER_NPCS_FILE,
                section="伙伴修士",
            ),
            enemies=_read_enemy_catalog(reader),
            world=_read_versioned(reader, WORLD_FILE),
        )
        _validate(content)
        return content

    @property
    def technique_definitions(self) -> dict[str, dict[str, Any]]:
        return self.techniques["功法"]

    @property
    def technique_groups(self) -> dict[str, tuple[str, ...]]:
        return self.techniques["分组"]

    @property
    def enchantment_groups(self) -> dict[str, tuple[str, ...]]:
        return self.weapon_augments["分组"]["附魔"]

    @property
    def gem_groups(self) -> dict[str, tuple[str, ...]]:
        return self.weapon_augments["分组"]["宝石"]

    @property
    def direction_groups(self) -> dict[str, tuple[str, ...]]:
        return self.directions["分组"]["方向"]

    @property
    def grade_definitions(self) -> dict[str, dict[str, Any]]:
        return self.grades["品级"]

    @property
    def affix_definitions(self) -> dict[str, dict[str, Any]]:
        return self.combat["词条"]

    @property
    def attribute_definitions(self) -> dict[str, dict[str, Any]]:
        return self.combat["属性"]

    @property
    def mechanism_definitions(self) -> dict[str, dict[str, Any]]:
        return self.combat["机制"]

    @property
    def atomic_ability_definitions(self) -> dict[str, dict[str, Any]]:
        return self.combat["原子能力"]

    @property
    def event_definitions(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.combat["事件"])

    @property
    def item_definitions(self) -> dict[str, dict[str, Any]]:
        return self.items["物品"]

    @property
    def enchantment_definitions(self) -> dict[str, dict[str, Any]]:
        return self.weapon_augments["附魔"]

    @property
    def gem_definitions(self) -> dict[str, dict[str, Any]]:
        return self.weapon_augments["宝石"]

    @property
    def direction_definitions(self) -> dict[str, dict[str, Any]]:
        return self.directions["方向"]

    @property
    def item_groups(self) -> dict[str, tuple[str, ...]]:
        return self.items["分组"]

    @property
    def item_categories(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.items["物品类别"])

    @property
    def npc_definitions(self) -> dict[str, dict[str, Any]]:
        return self.npcs["伙伴修士"]

    @property
    def npc_groups(self) -> dict[str, tuple[str, ...]]:
        return self.npcs["分组"]

    @property
    def npc_home_locations(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for location_id, definition in self.location_definitions.items():
            for npc_id in self.npcs_in_groups(list(definition["修士池"])):
                result[npc_id] = str(location_id)
        return result

    @property
    def enemy_definitions(self) -> dict[str, dict[str, Any]]:
        return self.enemies["敌人"]

    @property
    def enemy_groups(self) -> dict[str, tuple[str, ...]]:
        return self.enemies["分组"]

    @property
    def enemy_group_kinds(self) -> dict[str, str]:
        return self.enemies["分组类别"]

    @property
    def world_definition(self) -> dict[str, Any]:
        return self.world["世界"]

    @property
    def location_definitions(self) -> dict[str, dict[str, Any]]:
        return self.world["地点"]

    def npcs_in_groups(self, groups: list[str]) -> tuple[str, ...]:
        return _expand_groups(groups, self.npc_groups)

    def items_in_groups(self, groups: list[str]) -> tuple[str, ...]:
        return _expand_groups(groups, self.item_groups)

    def enemies_in_groups(self, groups: list[str]) -> tuple[str, ...]:
        return _expand_groups(groups, self.enemy_groups)

    def techniques_in_groups(self, groups: list[str]) -> tuple[str, ...]:
        return _expand_groups(groups, self.technique_groups)

    def enchantments_in_groups(self, groups: list[str]) -> tuple[str, ...]:
        return _expand_groups(groups, self.enchantment_groups)

    def gems_in_groups(self, groups: list[str]) -> tuple[str, ...]:
        return _expand_groups(groups, self.gem_groups)

    def directions_in_groups(self, groups: list[str]) -> tuple[str, ...]:
        return _expand_groups(groups, self.direction_groups)

    def direction_candidates(self, direction_id: str) -> dict[str, tuple[str, ...]]:
        definition = self.direction_definitions[str(direction_id)]
        return {
            "功法": self.techniques_in_groups(list(definition["功法池"])),
            "附魔": self.enchantments_in_groups(list(definition["附魔池"])),
            "宝石": self.gems_in_groups(list(definition["宝石池"])),
        }

    def choose_npc(self, npc_ids: tuple[str, ...], rng: Any) -> str:
        return _weighted_choice(npc_ids, self.npc_definitions, rng, "修士")

    def choose_enemy(self, enemy_ids: tuple[str, ...], rng: Any) -> str:
        return _weighted_choice(enemy_ids, self.enemy_definitions, rng, "敌人")

    def choose_item(self, item_ids: tuple[str, ...], rng: Any) -> str:
        return _weighted_choice(item_ids, self.item_definitions, rng, "物品")

    def choose_technique(self, technique_ids: tuple[str, ...], rng: Any) -> str:
        return _weighted_choice(technique_ids, self.technique_definitions, rng, "功法")

    def choose_enchantment(self, enchantment_ids: tuple[str, ...], rng: Any) -> str:
        return _weighted_choice(enchantment_ids, self.enchantment_definitions, rng, "附魔")

    def choose_gem(self, gem_ids: tuple[str, ...], rng: Any) -> str:
        return _weighted_choice(gem_ids, self.gem_definitions, rng, "宝石")

    def choose_direction(self, direction_ids: tuple[str, ...], rng: Any) -> str:
        return _weighted_choice(direction_ids, self.direction_definitions, rng, "方向")

    def choose_affix(self, affix_ids: tuple[str, ...], rng: Any) -> str:
        return _weighted_choice(affix_ids, self.affix_definitions, rng, "词条")

    def choose_grade(self, rng: Any) -> str:
        return _weighted_choice(tuple(self.grade_definitions), self.grade_definitions, rng, "品级")

    def grade_at_least(self, grade_id: str, minimum_grade_id: str) -> bool:
        current = self.grade_definitions[str(grade_id)]
        minimum = self.grade_definitions[str(minimum_grade_id)]
        return int(current["阶序"]) >= int(minimum["阶序"])

    def item_price(self, item_id: str, grade_id: str) -> int:
        item = self.item_definitions[str(item_id)]
        grade = self.grade_definitions[str(grade_id)]
        return max(0, int(float(item["参考价"]) * float(grade["价格系数"]) + 0.5))

    def graded_item_definition(self, item_id: str, grade_id: str) -> dict[str, Any]:
        item = dict(self.item_definitions[str(item_id)])
        grade = self.grade_definitions[str(grade_id)]
        multiplier = float(grade["能力倍率"])
        use = item.get("使用效果")
        if isinstance(use, dict):
            scaled_use = dict(use)
            if "恢复量" in use:
                scaled_use["恢复量"] = round(float(use["恢复量"]) * multiplier, 4)
            item["使用效果"] = scaled_use
        item.update(
            {
                "基础物品": str(item_id),
                "名称": f"{grade_id}·{item_id}",
                "品级": str(grade_id),
                "能力倍率": multiplier,
                "评分": int(float(item["评分"]) * multiplier + 0.5),
                "参考价": self.item_price(item_id, grade_id),
            }
        )
        return item

    def combat_item_definitions(self) -> dict[str, dict[str, Any]]:
        """展开全部品级物品；保留基础名以读取旧的活动预计算记录。"""

        result = {
            str(item_id): dict(definition)
            for item_id, definition in self.item_definitions.items()
        }
        for item_id in self.item_definitions:
            for grade_id in self.grade_definitions:
                definition = self.graded_item_definition(item_id, grade_id)
                result[str(definition["名称"])] = definition
        return result

    def configured_weapon_augment(
        self,
        kind: str,
        augment_id: str,
        grade_id: str,
        *,
        instance_id: str,
    ) -> dict[str, Any]:
        definitions = {
            "附魔": self.enchantment_definitions,
            "宝石": self.gem_definitions,
        }
        if kind not in definitions:
            raise GameContentError(f"未知本命武器增幅类型：{kind}")
        definition = definitions[kind][str(augment_id)]
        grade = self.grade_definitions[str(grade_id)]
        multiplier = float(grade["能力倍率"])
        return {
            "实例": str(instance_id),
            "类型": kind,
            "名称": str(augment_id),
            "品级": str(grade_id),
            "威力倍率": multiplier,
            "评分": int(float(definition["评分"]) * multiplier + 0.5),
            "能力": [dict(node) for node in definition["组成"]],
        }

    def attributes_at_level(
        self,
        attributes: dict[str, Any],
        growth: dict[str, Any],
        level: int,
    ) -> dict[str, float]:
        """按配置成长计算指定等级属性，不区分玩家、修士或灵兽。"""

        result = {str(key): float(value) for key, value in attributes.items()}
        gained_levels = max(0, int(level) - 1)
        for key, amount in growth.items():
            attribute = str(key)
            result[attribute] = result.get(attribute, 0.0) + gained_levels * float(amount)
        return result

    def ability_executor(self, node: dict[str, Any]) -> str:
        ability = str(node.get("能力") or "")
        try:
            return str(self.atomic_ability_definitions[ability]["执行器"])
        except KeyError as exc:
            raise GameContentError(f"未知原子能力：{ability or '<空>'}") from exc

    def configured_battle_techniques(
        self,
        definitions: list[dict[str, Any]],
        *,
        instance_prefix: str,
    ) -> list[dict[str, Any]]:
        """把 JSON 中的功法引用展开成战斗核心使用的统一实例。"""

        result: list[dict[str, Any]] = []
        for index, value in enumerate(definitions, start=1):
            technique_id = str(value["功法"])
            grade_id = str(value["品级"])
            technique = self.technique_definitions[technique_id]
            grade = self.grade_definitions[grade_id]
            affixes = []
            for raw_affix in value.get("词条") or ():
                affix_id = str(raw_affix["词条"])
                affix = self.affix_definitions[affix_id]
                affixes.append(
                    {
                        "词条": affix_id,
                        "属性": str(affix["属性"]),
                        "数值": float(raw_affix["数值"]),
                        "最小值": float(affix["最小值"]),
                        "最大值": float(affix["最大值"]),
                    }
                )
            result.append(
                {
                    "实例": f"{instance_prefix}:{index}",
                    "功法": technique_id,
                    "品级": grade_id,
                    "出生序号": index,
                    "威力倍率": float(grade["能力倍率"]),
                    "词条": affixes,
                    "能力": [dict(node) for node in technique.get("组成") or ()],
                }
            )
        return result


def _validate(content: GameContent) -> None:
    character = _require_object(content.player, "人物", PLAYER_FILE)
    weapon = _require_object(content.player, "本命武器", PLAYER_FILE)
    grades = _require_object(content.grades, "品级", GRADES_FILE)
    seclusion = _require_object(content.activities, "闭关", ACTIVITIES_FILE)
    exploration = _require_object(content.activities, "探险", ACTIVITIES_FILE)
    attributes = _require_object(content.combat, "属性", ATTRIBUTES_FILE)
    affixes = _require_object(content.combat, "词条", AFFIXES_FILE)
    abilities = _require_object(content.combat, "原子能力", ATOMIC_ABILITIES_FILE)
    mechanisms = _require_object(content.combat, "机制", MECHANISMS_FILE)
    techniques = _require_object(content.techniques, "功法", TECHNIQUES_FILE)
    items = _require_object(content.items, "物品", ITEMS_FILE)
    enchantments = _require_object(content.weapon_augments, "附魔", WEAPON_AUGMENTS_FILE)
    gems = _require_object(content.weapon_augments, "宝石", WEAPON_AUGMENTS_FILE)
    directions = _require_object(content.directions, "方向", DIRECTIONS_FILE)
    categories = _string_list(content.items.get("物品类别"), f"{ITEMS_FILE} -> 物品类别")
    npcs = _require_object(content.npcs, "伙伴修士", NPCS_FILE)
    enemies = _require_object(content.enemies, "敌人", ENEMIES_FILE)
    world = _require_object(content.world, "世界", WORLD_FILE)
    locations = _require_object(content.world, "地点", WORLD_FILE)

    validator = _validate_combat(content.combat, attributes, affixes, abilities, mechanisms)
    _validate_player(character, weapon, attributes, content.combat)
    _validate_activities(seclusion, exploration)
    _validate_grades(grades)
    _validate_techniques(techniques, grades, affixes, validator)
    _validate_weapon_augments(enchantments, gems, validator)
    _validate_items(items, categories, enchantments, gems)
    _validate_directions(
        directions,
        content.technique_groups,
        content.enchantment_groups,
        content.gem_groups,
        _require_object(content.player, "伙伴", PLAYER_FILE),
    )
    _validate_npcs(
        npcs,
        items,
        categories,
        grades,
        attributes,
        content.combat,
        content.direction_groups,
    )
    _validate_enemies(
        enemies,
        techniques,
        grades,
        affixes,
        attributes,
        content.combat,
        int(character["等级上限"]),
        content.enemy_groups,
        content.enemy_group_kinds,
        content.item_groups,
    )
    _validate_world(
        world,
        locations,
        content.npc_groups,
        content.enemy_groups,
        content.enemy_definitions,
    )

    starter_items = content.player.get("初始物品") or {}
    if not isinstance(starter_items, dict):
        raise GameContentError(f"数据文件有问题：{PLAYER_FILE} -> 初始物品：必须是对象")
    for item_id, quantity in starter_items.items():
        if item_id not in items:
            raise GameContentError(f"数据文件有问题：{PLAYER_FILE} -> 初始物品：未知物品 {item_id}")
        _integer(quantity, f"{PLAYER_FILE} -> 初始物品.{item_id}", minimum=1)


def _validate_combat(
    combat: dict[str, Any],
    attributes: dict[str, Any],
    affixes: dict[str, Any],
    abilities: dict[str, Any],
    mechanisms: dict[str, Any],
) -> RuleSchemaValidator:
    if not attributes:
        raise GameContentError(f"数据文件有问题：{ATTRIBUTES_FILE} -> 属性：不能为空")
    for attribute_id, definition in attributes.items():
        path = f"{ATTRIBUTES_FILE} -> 属性.{attribute_id}"
        value = _object(definition, path)
        _allow_only(value, path, {"默认值", "单位", "最小单位", "最低值", "最高值", "显示", "说明"})
        if not str(value.get("单位") or "").strip():
            raise GameContentError(f"数据文件有问题：{path}.单位：不能为空")
        _number(value.get("最小单位"), f"{path}.最小单位", minimum=0.0000001)
        minimum = _number(value.get("最低值"), f"{path}.最低值")
        maximum = _number(value.get("最高值"), f"{path}.最高值")
        if maximum < minimum:
            raise GameContentError(f"数据文件有问题：{path}：最高值不能小于最低值")
        _number(value.get("默认值"), f"{path}.默认值", minimum=minimum, maximum=maximum)
        if value.get("显示") not in {"数值", "百分比"}:
            raise GameContentError(f"数据文件有问题：{path}.显示：必须是数值或百分比")
        if not str(value.get("说明") or "").strip():
            raise GameContentError(f"数据文件有问题：{path}.说明：不能为空")

    for key in ("人物必需属性", "参战者必需属性"):
        required = _string_list(combat.get(key), f"{ATTRIBUTES_FILE} -> {key}")
        unknown = set(required) - set(attributes)
        if unknown:
            raise GameContentError(
                f"数据文件有问题：{ATTRIBUTES_FILE} -> {key}：未知属性 "
                + "、".join(sorted(unknown))
            )

    if not affixes:
        raise GameContentError(f"数据文件有问题：{AFFIXES_FILE} -> 词条：不能为空")
    for affix_id, definition in affixes.items():
        path = f"{AFFIXES_FILE} -> 词条.{affix_id}"
        value = _object(definition, path)
        _attribute(value.get("属性"), f"{path}.属性", attributes)
        minimum = _number(value.get("最小值"), f"{path}.最小值")
        maximum = _number(value.get("最大值"), f"{path}.最大值")
        if maximum < minimum:
            raise GameContentError(f"数据文件有问题：{path}：最大值不能小于最小值")
        _integer(value.get("权重"), f"{path}.权重", minimum=1)

    resources = _require_object(combat, "资源", RESOURCES_FILE)
    for resource_id, definition in resources.items():
        path = f"{RESOURCES_FILE} -> 资源.{resource_id}"
        value = _object(definition, path)
        _attribute(value.get("上限属性"), f"{path}.上限属性", attributes)
        _number(value.get("最低值"), f"{path}.最低值")

    damage_rules = _require_object(combat, "伤害规则", COMBAT_FLOW_FILE)
    damage_fields = (
        "基础命中率", "最低命中率", "最高命中率", "最高暴击倍率",
        "最高格挡率", "最高伤害倍率", "防御常数", "最低伤害",
    )
    for key in damage_fields:
        _number(damage_rules.get(key), f"{COMBAT_FLOW_FILE} -> 伤害规则.{key}", minimum=0)
    if float(damage_rules["最低命中率"]) > float(damage_rules["最高命中率"]):
        raise GameContentError(f"数据文件有问题：{COMBAT_FLOW_FILE} -> 伤害规则：命中率边界反向")

    action_rules = _require_object(combat, "行动规则", COMBAT_FLOW_FILE)
    baseline = _positive(action_rules.get("标准速度"), f"{COMBAT_FLOW_FILE} -> 行动规则.标准速度")
    minimum = _positive(action_rules.get("最低有效速度"), f"{COMBAT_FLOW_FILE} -> 行动规则.最低有效速度")
    _number(action_rules.get("最高行动效率"), f"{COMBAT_FLOW_FILE} -> 行动规则.最高行动效率", minimum=1.000001)
    if minimum > baseline:
        raise GameContentError(f"数据文件有问题：{COMBAT_FLOW_FILE} -> 行动规则：最低有效速度不能高于标准速度")

    events = _string_list(combat.get("事件"), f"{COMBAT_FLOW_FILE} -> 事件")
    validator = RuleSchemaValidator(
        abilities=abilities,
        executor_categories=EXECUTOR_CATEGORIES,
        attributes=attributes,
        resources=resources,
        events=events,
        mechanisms=mechanisms,
    )
    try:
        validator.validate_definitions()
        validator.validate_mechanisms()
    except RuleSchemaError as exc:
        raise GameContentError(f"数据文件有问题：{exc}") from exc
    return validator


def _validate_grades(grades: dict[str, Any]) -> None:
    expected = ("黄品", "玄品", "地品", "天品", "圣品")
    if tuple(grades) != expected:
        raise GameContentError(
            f"数据文件有问题：{GRADES_FILE} -> 品级：必须按顺序配置 " + "、".join(expected)
        )
    for expected_order, (grade_id, definition) in enumerate(grades.items(), start=1):
        path = f"{GRADES_FILE} -> 品级.{grade_id}"
        value = _object(definition, path)
        _allow_only(
            value,
            path,
            {"阶序", "权重", "能力倍率", "价格系数", "词条数量", "评分"},
        )
        order = _integer(value.get("阶序"), f"{path}.阶序", minimum=1)
        if order != expected_order:
            raise GameContentError(f"数据文件有问题：{path}.阶序：必须为 {expected_order}")
        _integer(value.get("权重"), f"{path}.权重", minimum=1)
        _positive(value.get("能力倍率"), f"{path}.能力倍率")
        _positive(value.get("价格系数"), f"{path}.价格系数")
        _integer(value.get("词条数量"), f"{path}.词条数量", minimum=0)
        _integer(value.get("评分"), f"{path}.评分", minimum=0)


def _validate_techniques(
    techniques: dict[str, Any],
    grades: dict[str, Any],
    affixes: dict[str, Any],
    validator: RuleSchemaValidator,
) -> None:
    if not techniques:
        raise GameContentError(f"数据文件有问题：{TECHNIQUES_FILE}：功法不能为空")
    maximum_affix_count = max(int(value["词条数量"]) for value in grades.values())
    if maximum_affix_count > len(affixes):
        raise GameContentError(f"数据文件有问题：{GRADES_FILE}：词条数量不能超过基础词条库数量")

    for technique_id, definition in techniques.items():
        path = f"{TECHNIQUES_FILE} -> 功法.{technique_id}"
        value = _object(definition, path)
        if not str(technique_id).strip():
            raise GameContentError(f"数据文件有问题：{path}：功法名不能为空")
        _allow_only(value, path, {"说明", "权重", "随机词条", "组成"})
        if not str(value.get("说明") or "").strip():
            raise GameContentError(f"数据文件有问题：{path}.说明：不能为空")
        _integer(value.get("权重"), f"{path}.权重", minimum=1)
        affix_ids = _string_list(value.get("随机词条"), f"{path}.随机词条")
        unknown_affixes = set(affix_ids) - set(affixes)
        if unknown_affixes:
            raise GameContentError(
                f"数据文件有问题：{path}.随机词条：未在 {AFFIXES_FILE} 注册 "
                + "、".join(sorted(unknown_affixes))
            )
        if len(affix_ids) < maximum_affix_count:
            raise GameContentError(
                f"数据文件有问题：{path}.随机词条：数量不足以承载最高品级的 {maximum_affix_count} 条词条"
            )
        composition = value.get("组成")
        if not isinstance(composition, list) or not composition:
            raise GameContentError(f"数据文件有问题：{path}.组成：必须是非空数组")
        executors: list[str] = []
        try:
            for index, node in enumerate(composition):
                node_path = f"{path}.组成[{index}]"
                validator.validate_node(node, node_path, allowed_categories={"装配"})
                executors.append(validator.executor_of(node, node_path))
        except RuleSchemaError as exc:
            raise GameContentError(f"数据文件有问题：{exc}") from exc
        if not {"装配主动技能", "装配被动技能"}.intersection(executors):
            raise GameContentError(f"数据文件有问题：{path}.组成：至少需要主动技能或被动技能")


def _validate_weapon_augments(
    enchantments: dict[str, Any],
    gems: dict[str, Any],
    validator: RuleSchemaValidator,
) -> None:
    for section, values in (("附魔", enchantments), ("宝石", gems)):
        if not values:
            raise GameContentError(f"数据文件有问题：{WEAPON_AUGMENTS_FILE} -> {section}：不能为空")
        for augment_id, definition in values.items():
            path = f"{WEAPON_AUGMENTS_FILE} -> {section}.{augment_id}"
            value = _object(definition, path)
            _allow_only(value, path, {"说明", "权重", "评分", "组成"})
            if not str(value.get("说明") or "").strip():
                raise GameContentError(f"数据文件有问题：{path}.说明：不能为空")
            _integer(value.get("权重"), f"{path}.权重", minimum=1)
            _integer(value.get("评分"), f"{path}.评分", minimum=0)
            composition = value.get("组成")
            if not isinstance(composition, list) or not composition:
                raise GameContentError(f"数据文件有问题：{path}.组成：必须是非空数组")
            try:
                for index, node in enumerate(composition):
                    validator.validate_node(
                        node,
                        f"{path}.组成[{index}]",
                        allowed_categories={"装配"},
                    )
            except RuleSchemaError as exc:
                raise GameContentError(f"数据文件有问题：{exc}") from exc


def _validate_directions(
    directions: dict[str, Any],
    technique_groups: dict[str, tuple[str, ...]],
    enchantment_groups: dict[str, tuple[str, ...]],
    gem_groups: dict[str, tuple[str, ...]],
    partner_rules: dict[str, Any],
) -> None:
    _allow_only(
        partner_rules,
        f"{PLAYER_FILE} -> 伙伴",
        {"功法位", "附魔位", "宝石位", "好感上限"},
    )
    _integer(
        partner_rules.get("好感上限"),
        f"{PLAYER_FILE} -> 伙伴.好感上限",
        minimum=1,
    )
    limits = {
        "功法池": _integer(partner_rules.get("功法位"), f"{PLAYER_FILE} -> 伙伴.功法位", minimum=1),
        "附魔池": _integer(partner_rules.get("附魔位"), f"{PLAYER_FILE} -> 伙伴.附魔位", minimum=1),
        "宝石池": _integer(partner_rules.get("宝石位"), f"{PLAYER_FILE} -> 伙伴.宝石位", minimum=1),
    }
    catalogs = {
        "功法池": technique_groups,
        "附魔池": enchantment_groups,
        "宝石池": gem_groups,
    }
    if not directions:
        raise GameContentError(f"数据文件有问题：{DIRECTIONS_FILE} -> 方向：不能为空")
    for direction_id, definition in directions.items():
        path = f"{DIRECTIONS_FILE} -> 方向.{direction_id}"
        value = _object(definition, path)
        _allow_only(value, path, {"说明", "权重", "资质范围", "功法池", "附魔池", "宝石池"})
        if not str(value.get("说明") or "").strip():
            raise GameContentError(f"数据文件有问题：{path}.说明：不能为空")
        _integer(value.get("权重"), f"{path}.权重", minimum=1)
        _range(value.get("资质范围"), f"{path}.资质范围", minimum=1)
        for pool_name, groups in catalogs.items():
            pool_files = _string_list(value.get(pool_name), f"{path}.{pool_name}")
            unknown = set(pool_files) - set(groups)
            if unknown:
                raise GameContentError(
                    f"数据文件有问题：{path}.{pool_name}：引用不存在的 JSON 文件 "
                    + "、".join(sorted(unknown))
                )
            pool = _expand_groups(pool_files, groups)
            if len(pool) < limits[pool_name]:
                raise GameContentError(
                    f"数据文件有问题：{path}.{pool_name}：展开后至少需要 {limits[pool_name]} 项"
                )


def _validate_items(
    items: dict[str, Any],
    categories: list[str],
    enchantments: dict[str, Any],
    gems: dict[str, Any],
) -> None:
    required_categories = {
        "功法",
        "丹药",
        "附魔技能书",
        "宝石",
        "灵兽材料",
        "天材地宝",
        "修行器物",
    }
    missing_categories = required_categories - set(categories)
    if missing_categories:
        raise GameContentError(
            f"数据文件有问题：{ITEMS_FILE} -> 物品类别：缺少"
            + "、".join(sorted(missing_categories))
        )

    augment_links = {
        "附魔技能书": ("对应附魔", enchantments),
        "宝石": ("对应宝石", gems),
    }
    linked_augments: dict[str, dict[str, str]] = {
        category: {} for category in augment_links
    }
    category_counts = {category: 0 for category in categories if category != "功法"}
    for item_id, definition in items.items():
        path = f"{ITEMS_FILE} -> 物品.{item_id}"
        value = _object(definition, path)
        _allow_only(
            value,
            path,
            {
                "类别",
                "说明",
                "权重",
                "可堆叠",
                "使用效果",
                "对应附魔",
                "对应宝石",
                "评分",
                "参考价",
            },
        )
        category = str(value.get("类别") or "")
        if category not in categories or category == "功法":
            raise GameContentError(f"数据文件有问题：{path}.类别：未知或不可用类别 {category}")
        category_counts[category] += 1
        if not str(value.get("说明") or "").strip():
            raise GameContentError(f"数据文件有问题：{path}.说明：不能为空")
        _integer(value.get("权重"), f"{path}.权重", minimum=1)
        if not isinstance(value.get("可堆叠"), bool):
            raise GameContentError(f"数据文件有问题：{path}.可堆叠：必须是布尔值")
        _integer(value.get("评分"), f"{path}.评分", minimum=0)
        _integer(value.get("参考价"), f"{path}.参考价", minimum=0)

        link = augment_links.get(category)
        if link is None:
            unexpected_links = {"对应附魔", "对应宝石"}.intersection(value)
            if unexpected_links:
                raise GameContentError(
                    f"数据文件有问题：{path}：{category}不能填写"
                    + "、".join(sorted(unexpected_links))
                )
        else:
            field, catalog = link
            other_field = "对应宝石" if field == "对应附魔" else "对应附魔"
            if other_field in value:
                raise GameContentError(f"数据文件有问题：{path}.{other_field}：物品类别不匹配")
            augment_id = str(value.get(field) or "").strip()
            if augment_id not in catalog:
                raise GameContentError(
                    f"数据文件有问题：{path}.{field}：引用不存在的{category} {augment_id or '<空>'}"
                )
            previous = linked_augments[category].get(augment_id)
            if previous is not None:
                raise GameContentError(
                    f"数据文件有问题：{path}.{field}：{augment_id}已由{previous}对应"
                )
            linked_augments[category][augment_id] = str(item_id)
            for field_name in ("权重", "评分"):
                if value[field_name] != catalog[augment_id][field_name]:
                    raise GameContentError(
                        f"数据文件有问题：{path}.{field_name}：必须与{augment_id}的{field_name}一致"
                    )

        use = value.get("使用效果")
        if use is not None:
            use_value = _object(use, f"{path}.使用效果")
            if category == "丹药":
                _allow_only(use_value, f"{path}.使用效果", {"类型", "恢复量"})
                if use_value.get("类型") not in {"恢复血气", "恢复精神"}:
                    raise GameContentError(f"数据文件有问题：{path}.使用效果.类型：未知丹药效果")
                _positive(use_value.get("恢复量"), f"{path}.使用效果.恢复量")
            elif category == "修行器物":
                _allow_only(use_value, f"{path}.使用效果", {"类型", "经验"})
                if use_value.get("类型") not in {
                    "增加人物经验",
                    "增加本命武器经验",
                    "增加伙伴经验",
                }:
                    raise GameContentError(f"数据文件有问题：{path}.使用效果.类型：未知修行器物效果")
                _integer(use_value.get("经验"), f"{path}.使用效果.经验", minimum=1)
            else:
                raise GameContentError(
                    f"数据文件有问题：{path}.使用效果：{category}不能直接使用"
                )

    empty_categories = [category for category, count in category_counts.items() if count == 0]
    if empty_categories:
        raise GameContentError(
            f"数据文件有问题：{ITEMS_FILE} -> 物品：类别不能为空 "
            + "、".join(empty_categories)
        )
    for category, (_, catalog) in augment_links.items():
        missing = set(catalog) - set(linked_augments[category])
        if missing:
            raise GameContentError(
                f"数据文件有问题：{ITEMS_FILE} -> {category}：缺少对应物品 "
                + "、".join(sorted(missing))
            )


def _validate_npcs(
    npcs: dict[str, Any],
    items: dict[str, Any],
    item_categories: list[str],
    grades: dict[str, Any],
    attribute_definitions: dict[str, Any],
    combat: dict[str, Any],
    direction_groups: dict[str, tuple[str, ...]],
) -> None:
    if not npcs:
        raise GameContentError(f"数据文件有问题：{NPCS_FILE} -> 伙伴修士：不能为空")
    required = set(
        _string_list(
            combat.get("参战者必需属性"),
            f"{ATTRIBUTES_FILE} -> 参战者必需属性",
        )
    )
    for npc_id, definition in npcs.items():
        path = f"{NPCS_FILE} -> 伙伴修士.{npc_id}"
        value = _object(definition, path)
        _allow_only(
            value,
            path,
            {
                "身份",
                "说明",
                "权重",
                "等级",
                "实力波动",
                "属性",
                "方向池",
                "结交",
            },
        )
        identity = _require_object(value, "身份", path)
        _allow_only(identity, f"{path}.身份", {"称号", "立场", "可交互", "话语"})
        for key in ("称号", "立场"):
            if not str(identity.get(key) or "").strip():
                raise GameContentError(f"数据文件有问题：{path}.身份.{key}：不能为空")
        if not isinstance(identity.get("可交互"), bool):
            raise GameContentError(f"数据文件有问题：{path}.身份.可交互：必须是布尔值")
        dialogue = _string_list(identity.get("话语"), f"{path}.身份.话语")
        if identity["可交互"] and not dialogue:
            raise GameContentError(f"数据文件有问题：{path}.身份.话语：可交互修士不能为空")
        if not str(value.get("说明") or "").strip():
            raise GameContentError(f"数据文件有问题：{path}.说明：不能为空")
        _integer(value.get("权重"), f"{path}.权重", minimum=1)
        direction_pool = _string_list(value.get("方向池"), f"{path}.方向池")
        unknown_directions = set(direction_pool) - set(direction_groups)
        if unknown_directions:
            raise GameContentError(
                f"数据文件有问题：{path}.方向池：引用不存在的 JSON 文件 "
                + "、".join(sorted(unknown_directions))
            )
        if not _expand_groups(direction_pool, direction_groups):
            raise GameContentError(f"数据文件有问题：{path}.方向池：展开后不能为空")
        relationship = _require_object(value, "结交", path)
        relationship_path = f"{path}.结交"
        _allow_only(
            relationship,
            relationship_path,
            {
                "喜爱类别",
                "偏爱物品",
                "偏爱加成",
                "圆满回礼",
                "入队话语",
                "离队话语",
            },
        )
        liked_categories = _string_list(
            relationship.get("喜爱类别"),
            f"{relationship_path}.喜爱类别",
        )
        if not liked_categories:
            raise GameContentError(f"数据文件有问题：{relationship_path}.喜爱类别：不能为空")
        unknown_categories = set(liked_categories) - set(item_categories)
        if unknown_categories or "功法" in liked_categories:
            raise GameContentError(
                f"数据文件有问题：{relationship_path}.喜爱类别：不可赠送类别 "
                + "、".join(sorted(unknown_categories or {"功法"}))
            )
        favorite_items = _string_list(
            relationship.get("偏爱物品"),
            f"{relationship_path}.偏爱物品",
        )
        if not favorite_items:
            raise GameContentError(f"数据文件有问题：{relationship_path}.偏爱物品：不能为空")
        unknown_items = set(favorite_items) - set(items)
        if unknown_items:
            raise GameContentError(
                f"数据文件有问题：{relationship_path}.偏爱物品：未知物品 "
                + "、".join(sorted(unknown_items))
            )
        mismatched_items = {
            item_id
            for item_id in favorite_items
            if str(items[item_id]["类别"]) not in liked_categories
        }
        if mismatched_items:
            raise GameContentError(
                f"数据文件有问题：{relationship_path}.偏爱物品：类别不在喜爱类别中 "
                + "、".join(sorted(mismatched_items))
            )
        _integer(
            relationship.get("偏爱加成"),
            f"{relationship_path}.偏爱加成",
            minimum=0,
            maximum=500,
        )
        reward = _require_object(relationship, "圆满回礼", relationship_path)
        reward_path = f"{relationship_path}.圆满回礼"
        _allow_only(reward, reward_path, {"物品", "品级", "数量"})
        reward_item = str(reward.get("物品") or "")
        reward_grade = str(reward.get("品级") or "")
        if reward_item not in items:
            raise GameContentError(f"数据文件有问题：{reward_path}.物品：未知物品 {reward_item}")
        if reward_grade not in grades:
            raise GameContentError(f"数据文件有问题：{reward_path}.品级：未知品级 {reward_grade}")
        _integer(reward.get("数量"), f"{reward_path}.数量", minimum=1)
        for line_key in ("入队话语", "离队话语"):
            if not str(relationship.get(line_key) or "").strip():
                raise GameContentError(f"数据文件有问题：{relationship_path}.{line_key}：不能为空")
        level = _integer(value.get("等级"), f"{path}.等级", minimum=1)
        if level != 1:
            raise GameContentError(f"数据文件有问题：{path}.等级：伙伴候选必须从 1 级开始")
        attributes = _require_object(value, "属性", path)
        missing = required - set(attributes)
        if missing:
            raise GameContentError(f"数据文件有问题：{path}.属性：缺少 " + "、".join(sorted(missing)))
        for key, amount in attributes.items():
            _attribute_amount(key, amount, attribute_definitions, f"{path}.属性.{key}")
        _validate_strength_variation(
            value.get("实力波动"),
            f"{path}.实力波动",
            attributes,
            attribute_definitions,
        )


def _validate_weapon(value: dict[str, Any], path: str) -> None:
    weapon = _require_object(value, "本命武器", path)
    _allow_only(weapon, f"{path}.本命武器", {"名称", "攻击"})
    if not str(weapon.get("名称") or "").strip():
        raise GameContentError(f"数据文件有问题：{path}.本命武器.名称：不能为空")
    _number(weapon.get("攻击"), f"{path}.本命武器.攻击", minimum=0)


def _validate_equipped_techniques(
    value: dict[str, Any],
    path: str,
    techniques: dict[str, Any],
    grades: dict[str, Any],
    affixes: dict[str, Any],
) -> None:
    equipped = value.get("功法")
    if not isinstance(equipped, list) or not equipped:
        raise GameContentError(f"数据文件有问题：{path}.功法：至少配置一门功法")
    if len(equipped) > 6:
        raise GameContentError(f"数据文件有问题：{path}.功法：最多同时装配六门")
    for index, raw_technique in enumerate(equipped):
        technique_path = f"{path}.功法[{index}]"
        technique = _object(raw_technique, technique_path)
        _allow_only(technique, technique_path, {"功法", "品级", "词条"})
        technique_id = str(technique.get("功法") or "")
        grade_id = str(technique.get("品级") or "")
        if technique_id not in techniques:
            raise GameContentError(f"数据文件有问题：{technique_path}.功法：未知功法 {technique_id}")
        if grade_id not in grades:
            raise GameContentError(f"数据文件有问题：{technique_path}.品级：未知品级 {grade_id}")
        configured_affixes = technique.get("词条") or []
        if not isinstance(configured_affixes, list):
            raise GameContentError(f"数据文件有问题：{technique_path}.词条：必须是数组")
        expected = int(grades[grade_id]["词条数量"])
        if len(configured_affixes) != expected:
            raise GameContentError(
                f"数据文件有问题：{technique_path}.词条：{grade_id}必须配置 {expected} 条"
            )
        used_affixes: set[str] = set()
        for affix_index, raw_affix in enumerate(configured_affixes):
            affix_path = f"{technique_path}.词条[{affix_index}]"
            configured_affix = _object(raw_affix, affix_path)
            _allow_only(configured_affix, affix_path, {"词条", "数值"})
            affix_id = str(configured_affix.get("词条") or "")
            if affix_id not in affixes:
                raise GameContentError(f"数据文件有问题：{affix_path}.词条：未知词条 {affix_id}")
            if affix_id in used_affixes:
                raise GameContentError(f"数据文件有问题：{technique_path}.词条：不能重复 {affix_id}")
            used_affixes.add(affix_id)
            affix = affixes[affix_id]
            _number(
                configured_affix.get("数值"),
                f"{affix_path}.数值",
                minimum=float(affix["最小值"]),
                maximum=float(affix["最大值"]),
            )


def _validate_combat_strategy(value: dict[str, Any], path: str) -> None:
    strategy = _require_object(value, "战斗策略", path)
    _allow_only(strategy, f"{path}.战斗策略", {"用药概率", "用药阈值"})
    _number(strategy.get("用药概率"), f"{path}.战斗策略.用药概率", minimum=0, maximum=1)
    _number(strategy.get("用药阈值"), f"{path}.战斗策略.用药阈值", minimum=0, maximum=1)


def _validate_loot_pool(
    value: dict[str, Any],
    path: str,
    item_groups: dict[str, tuple[str, ...]],
) -> None:
    _allow_only(value, path, {"灵石", "物品池"})
    _range(value.get("灵石"), f"{path}.灵石")
    pool_files = _string_list(value.get("物品池"), f"{path}.物品池")
    unknown = set(pool_files) - set(item_groups)
    if unknown:
        raise GameContentError(
            f"数据文件有问题：{path}.物品池：引用不存在的物品 JSON "
            + "、".join(sorted(unknown))
        )
    if not _expand_groups(pool_files, item_groups):
        raise GameContentError(f"数据文件有问题：{path}.物品池：展开后不能为空")


def _validate_enemies(
    enemies: dict[str, Any],
    techniques: dict[str, Any],
    grades: dict[str, Any],
    affixes: dict[str, Any],
    attribute_definitions: dict[str, Any],
    combat: dict[str, Any],
    maximum_level: int,
    enemy_groups: dict[str, tuple[str, ...]],
    enemy_group_kinds: dict[str, str],
    item_groups: dict[str, tuple[str, ...]],
) -> None:
    if not enemies:
        raise GameContentError(f"数据文件有问题：{ENEMIES_FILE} -> 敌人：不能为空")
    for group_id, enemy_ids in enemy_groups.items():
        expected_kind = enemy_group_kinds[group_id]
        for enemy_id in enemy_ids:
            is_cultivator = str(enemies[enemy_id].get("类别") or "") == "修士"
            if expected_kind == "敌对修士" and not is_cultivator:
                raise GameContentError(
                    f"数据文件有问题：{HOSTILE_CULTIVATORS_FILE}/{group_id}.json："
                    f"敌对修士文件不能放入 {enemy_id}"
                )
            if expected_kind == "灵兽" and is_cultivator:
                raise GameContentError(
                    f"数据文件有问题：{BEASTS_FILE}/{group_id}.json：灵兽文件不能放入修士 {enemy_id}"
                )
    required = set(
        _string_list(
            combat.get("参战者必需属性"),
            f"{ATTRIBUTES_FILE} -> 参战者必需属性",
        )
    )
    for enemy_id, definition in enemies.items():
        path = f"{ENEMIES_FILE} -> 敌人.{enemy_id}"
        value = _object(definition, path)
        _allow_only(
            value,
            path,
            {
                "类别",
                "说明",
                "权重",
                "等级",
                "实力波动",
                "属性",
                "每级成长",
                "掉落",
                "本命武器",
                "功法",
                "战斗策略",
                "交锋所得",
            },
        )
        for key in ("类别", "说明"):
            if not str(value.get(key) or "").strip():
                raise GameContentError(f"数据文件有问题：{path}.{key}：不能为空")
        _integer(value.get("权重"), f"{path}.权重", minimum=1)
        _level_range(value.get("等级"), f"{path}.等级", maximum_level)
        attributes = _require_object(value, "属性", path)
        missing = required - set(attributes)
        if missing:
            raise GameContentError(
                f"数据文件有问题：{path}.属性：缺少 " + "、".join(sorted(missing))
            )
        for key, amount in attributes.items():
            _attribute_amount(key, amount, attribute_definitions, f"{path}.属性.{key}")
        _validate_strength_variation(
            value.get("实力波动"),
            f"{path}.实力波动",
            attributes,
            attribute_definitions,
        )
        _validate_loot_pool(
            _require_object(value, "掉落", path),
            f"{path}.掉落",
            item_groups,
        )
        if str(value["类别"]) == "修士":
            if "每级成长" in value:
                raise GameContentError(
                    f"数据文件有问题：{path}.每级成长：敌对修士必须复用人物每级成长"
                )
            _validate_weapon(value, path)
            _validate_equipped_techniques(value, path, techniques, grades, affixes)
            _validate_combat_strategy(value, path)
        else:
            forbidden = {"本命武器", "功法", "战斗策略"}.intersection(value)
            if forbidden:
                raise GameContentError(
                    f"数据文件有问题：{path}：{value['类别']}不能配置 "
                    + "、".join(sorted(forbidden))
                )
            growth = _require_object(value, "每级成长", path)
            for key, amount in growth.items():
                _attribute(key, f"{path}.每级成长.{key}", attribute_definitions)
                _number(amount, f"{path}.每级成长.{key}")
        gains = _require_object(value, "交锋所得", path)
        _allow_only(gains, f"{path}.交锋所得", {"本命武器经验"})
        _range(gains.get("本命武器经验"), f"{path}.交锋所得.本命武器经验")


def _validate_strength_variation(
    raw: Any,
    path: str,
    attributes: dict[str, Any],
    attribute_definitions: dict[str, Any],
) -> None:
    variation = _object(raw, path)
    _allow_only(variation, path, {"属性", "倍率"})
    varied = _string_list(variation.get("属性"), f"{path}.属性")
    for key in varied:
        _attribute(key, f"{path}.属性.{key}", attribute_definitions)
        if key not in attributes:
            raise GameContentError(f"数据文件有问题：{path}.属性：基础属性中没有 {key}")
    minimum, maximum = _range(variation.get("倍率"), f"{path}.倍率", minimum=1)
    if maximum > 500:
        raise GameContentError(f"数据文件有问题：{path}.倍率：不能大于 500")


def _level_range(value: Any, path: str, maximum_level: int) -> tuple[int, int]:
    if isinstance(value, int) and not isinstance(value, bool):
        low = high = _integer(value, path, minimum=1)
    else:
        low, high = _range(value, path, minimum=1)
    if high > maximum_level:
        raise GameContentError(f"数据文件有问题：{path}：不能超过人物等级上限 {maximum_level}")
    return low, high


def _validate_player(
    character: dict[str, Any],
    weapon: dict[str, Any],
    attribute_definitions: dict[str, Any],
    combat: dict[str, Any],
) -> None:
    attributes = _require_object(character, "属性", f"{PLAYER_FILE} -> 人物")
    required = set(_string_list(combat.get("人物必需属性"), f"{ATTRIBUTES_FILE} -> 人物必需属性"))
    missing = required - set(attributes)
    if missing:
        raise GameContentError(
            f"数据文件有问题：{PLAYER_FILE} -> 人物.属性：缺少基础属性 "
            + "、".join(sorted(missing))
        )
    for key, amount in attributes.items():
        _attribute_amount(key, amount, attribute_definitions, f"{PLAYER_FILE} -> 人物.属性.{key}")
    growth = _require_object(character, "每级成长", f"{PLAYER_FILE} -> 人物")
    for key, amount in growth.items():
        _attribute(key, f"{PLAYER_FILE} -> 人物.每级成长.{key}", attribute_definitions)
        _number(amount, f"{PLAYER_FILE} -> 人物.每级成长.{key}")
    _integer(character.get("初始等级"), f"{PLAYER_FILE} -> 人物.初始等级", minimum=1)
    _integer(character.get("初始灵石"), f"{PLAYER_FILE} -> 人物.初始灵石", minimum=0)
    _integer(character.get("等级上限"), f"{PLAYER_FILE} -> 人物.等级上限", minimum=1)
    _integer(character.get("突破间隔"), f"{PLAYER_FILE} -> 人物.突破间隔", minimum=1)
    _validate_experience(_require_object(character, "经验", f"{PLAYER_FILE} -> 人物"), "人物")

    _integer(weapon.get("初始等级"), f"{PLAYER_FILE} -> 本命武器.初始等级", minimum=1)
    _integer(weapon.get("等级上限"), f"{PLAYER_FILE} -> 本命武器.等级上限", minimum=1)
    _positive(weapon.get("基础攻击"), f"{PLAYER_FILE} -> 本命武器.基础攻击")
    _number(weapon.get("每级攻击"), f"{PLAYER_FILE} -> 本命武器.每级攻击", minimum=0)
    _integer(weapon.get("附魔位"), f"{PLAYER_FILE} -> 本命武器.附魔位", minimum=1)
    _integer(weapon.get("宝石位"), f"{PLAYER_FILE} -> 本命武器.宝石位", minimum=1)
    _validate_experience(_require_object(weapon, "经验", f"{PLAYER_FILE} -> 本命武器"), "本命武器")


def _validate_experience(value: dict[str, Any], owner: str) -> None:
    _positive(value.get("基础"), f"{PLAYER_FILE} -> {owner}.经验.基础")
    _number(value.get("等级平方系数"), f"{PLAYER_FILE} -> {owner}.经验.等级平方系数", minimum=0)


def _validate_activities(seclusion: dict[str, Any], exploration: dict[str, Any]) -> None:
    for name, value in (("闭关", seclusion), ("探险", exploration)):
        path = f"{ACTIVITIES_FILE} -> {name}"
        duration = _integer(value.get("持续秒数"), f"{path}.持续秒数", minimum=1)
        round_seconds = _integer(value.get("每轮秒数"), f"{path}.每轮秒数", minimum=1)
        if duration % round_seconds:
            raise GameContentError(f"数据文件有问题：{path}：总时长必须能被轮次时长整除")
    maximum = _integer(exploration.get("最多轮数"), f"{ACTIVITIES_FILE} -> 探险.最多轮数", minimum=1)
    available = int(exploration["持续秒数"]) // int(exploration["每轮秒数"])
    if maximum != available:
        raise GameContentError(f"数据文件有问题：{ACTIVITIES_FILE} -> 探险.最多轮数：必须等于完整轮数")
    _positive(seclusion.get("每轮经验"), f"{ACTIVITIES_FILE} -> 闭关.每轮经验")
    _number(seclusion.get("感悟功法概率"), f"{ACTIVITIES_FILE} -> 闭关.感悟功法概率", minimum=0, maximum=1)
    if not isinstance(seclusion.get("圆满时清除临时状态"), bool):
        raise GameContentError(f"数据文件有问题：{ACTIVITIES_FILE} -> 闭关.圆满时清除临时状态：必须是布尔值")
    _positive(exploration.get("每轮体力消耗"), f"{ACTIVITIES_FILE} -> 探险.每轮体力消耗")
    _integer(exploration.get("战斗行动上限"), f"{ACTIVITIES_FILE} -> 探险.战斗行动上限", minimum=1)
    _number(exploration.get("自动用药阈值"), f"{ACTIVITIES_FILE} -> 探险.自动用药阈值", minimum=0, maximum=1)


def _validate_world(
    world: dict[str, Any],
    locations: dict[str, Any],
    npc_groups: dict[str, tuple[str, ...]],
    enemy_groups: dict[str, tuple[str, ...]],
    enemies: dict[str, dict[str, Any]],
) -> None:
    if not str(world.get("名称") or "").strip():
        raise GameContentError(f"数据文件有问题：{WORLD_FILE} -> 世界.名称：不能为空")
    if not str(world.get("说明") or "").strip():
        raise GameContentError(f"数据文件有问题：{WORLD_FILE} -> 世界.说明：不能为空")
    if not locations:
        raise GameContentError(f"数据文件有问题：{WORLD_FILE} -> 地点：不能为空")
    starting_location = str(world.get("出生地") or "")
    if starting_location not in locations:
        raise GameContentError(f"数据文件有问题：{WORLD_FILE} -> 世界.出生地：未知地点 {starting_location or '<空>'}")

    bounds = _require_object(world, "坐标边界", f"{WORLD_FILE} -> 世界")
    minimum_x, maximum_x = _range(bounds.get("横轴"), f"{WORLD_FILE} -> 世界.坐标边界.横轴", minimum=None)
    minimum_y, maximum_y = _range(bounds.get("纵轴"), f"{WORLD_FILE} -> 世界.坐标边界.纵轴", minimum=None)
    available_functions: set[str] = set()
    coordinates: dict[tuple[int, int], str] = {}
    npc_homes: dict[str, str] = {}
    for location_id, definition in locations.items():
        path = f"{WORLD_FILE} -> 地点.{location_id}"
        value = _object(definition, path)
        for key in ("地貌", "说明"):
            if not str(value.get(key) or "").strip():
                raise GameContentError(f"数据文件有问题：{path}.{key}：不能为空")
        functions = _string_list(value.get("可用功能"), f"{path}.可用功能")
        unknown = set(functions) - {"闭关", "探险", "修士"}
        if unknown:
            raise GameContentError(f"数据文件有问题：{path}.可用功能：未知功能 " + "、".join(sorted(unknown)))
        available_functions.update(functions)
        x, y = _coordinate(value.get("坐标"), f"{path}.坐标")
        if not minimum_x <= x <= maximum_x or not minimum_y <= y <= maximum_y:
            raise GameContentError(f"数据文件有问题：{path}.坐标：超出世界坐标边界")
        previous = coordinates.get((x, y))
        if previous is not None:
            raise GameContentError(f"数据文件有问题：{path}.坐标：与地点 {previous} 重复")
        coordinates[(x, y)] = str(location_id)
        npc_pool = _string_list(value.get("修士池"), f"{path}.修士池")
        if "修士" in functions and not npc_pool:
            raise GameContentError(f"数据文件有问题：{path}.修士池：修士功能地点不能为空")
        if npc_pool and "修士" not in functions:
            raise GameContentError(f"数据文件有问题：{path}.修士池：必须先在可用功能中启用修士")
        for group_id in npc_pool:
            if group_id not in npc_groups:
                raise GameContentError(
                    f"数据文件有问题：{path}.修士池：没有角色文件 {group_id}.json"
                )
            expected_group = f"伙伴修士-{location_id}"
            if group_id != expected_group:
                raise GameContentError(
                    f"数据文件有问题：{path}.修士池：伙伴修士必须按原始地点放入 "
                    f"{expected_group}.json"
                )
            for npc_id in npc_groups[group_id]:
                previous_home = npc_homes.get(npc_id)
                if previous_home is not None:
                    raise GameContentError(
                        f"数据文件有问题：{path}.修士池：{npc_id} 已属于地点 {previous_home}"
                    )
                npc_homes[npc_id] = str(location_id)
        enemy_pool = _string_list(value.get("敌人池"), f"{path}.敌人池")
        if "探险" in functions and not enemy_pool:
            raise GameContentError(f"数据文件有问题：{path}.敌人池：探险地点不能为空")
        if enemy_pool and "探险" not in functions:
            raise GameContentError(f"数据文件有问题：{path}.敌人池：必须先在可用功能中启用探险")
        for group_id in enemy_pool:
            if group_id not in enemy_groups:
                raise GameContentError(
                    f"数据文件有问题：{path}.敌人池：没有敌人文件 {group_id}.json"
                )
            cultivators = [
                enemy_id
                for enemy_id in enemy_groups[group_id]
                if str(enemies[enemy_id]["类别"]) == "修士"
            ]
            if cultivators:
                raise GameContentError(
                    f"数据文件有问题：{path}.敌人池：普通地点不能引用敌对修士 "
                    + "、".join(cultivators)
                )
    for required in ("闭关", "探险", "修士"):
        if required not in available_functions:
            raise GameContentError(f"数据文件有问题：{WORLD_FILE}：没有地点提供{required}")
    unplaced_npcs = {
        npc_id
        for npc_ids in npc_groups.values()
        for npc_id in npc_ids
        if npc_id not in npc_homes
    }
    if unplaced_npcs:
        raise GameContentError(
            f"数据文件有问题：{WORLD_FILE} -> 地点：伙伴修士没有原始地点 "
            + "、".join(sorted(unplaced_npcs))
        )


def _read_versioned(reader: JsonDataReader, path: str) -> dict[str, Any]:
    value = _object(reader.read(path), path)
    _require_version(value, path)
    return value


def _read_technique_catalog(reader: JsonDataReader) -> dict[str, Any]:
    techniques: dict[str, Any] = {}
    technique_sources: dict[str, str] = {}
    groups: dict[str, tuple[str, ...]] = {}
    for file_path, raw in reader.read_directory(TECHNIQUES_FILE):
        value = _object(raw, file_path)
        _require_version(value, file_path)
        if set(value) != {"版本", "功法"}:
            raise GameContentError(
                f"数据文件有问题：{file_path}：功法文件只能包含版本和功法"
            )
        values = _require_object(value, "功法", file_path)
        group_id = file_path.rsplit("/", 1)[-1].removesuffix(".json")
        groups[group_id] = tuple(str(key) for key in values)
        _merge_unique(
            techniques,
            technique_sources,
            values,
            file_path,
            "功法",
        )
    return {
        "版本": "目录展开",
        "功法": techniques,
        "分组": groups,
    }


def _read_item_catalog(
    reader: JsonDataReader,
    weapon_augments: dict[str, Any],
) -> dict[str, Any]:
    categories: list[str] = []
    items: dict[str, Any] = {}
    sources: dict[str, str] = {}
    groups: dict[str, tuple[str, ...]] = {}
    for file_path, raw in reader.read_directory(ITEMS_FILE):
        if file_path.startswith(f"{TECHNIQUES_FILE}/") or file_path.startswith(
            f"{ENCHANTMENTS_FILE}/"
        ) or file_path.startswith(f"{GEMS_FILE}/"):
            continue
        value = _object(raw, file_path)
        _require_version(value, file_path)
        _allow_only(value, file_path, {"版本", "物品类别", "物品"})
        if set(value) == {"版本"}:
            raise GameContentError(f"数据文件有问题：{file_path}：没有物品类别或物品")
        if "物品类别" in value:
            for category in _string_list(value["物品类别"], f"{file_path} -> 物品类别"):
                if category in categories:
                    raise GameContentError(f"数据文件有问题：{file_path} -> 物品类别：重复 {category}")
                categories.append(category)
        if "物品" in value:
            values = _require_object(value, "物品", file_path)
            group_id = file_path.rsplit("/", 1)[-1].removesuffix(".json")
            groups[group_id] = tuple(str(key) for key in values)
            _merge_unique(
                items,
                sources,
                values,
                file_path,
                "物品",
            )
    _append_weapon_augment_items(items, sources, groups, weapon_augments)
    return {
        "版本": "目录展开",
        "物品类别": categories,
        "物品": items,
        "分组": groups,
    }


def _append_weapon_augment_items(
    items: dict[str, Any],
    sources: dict[str, str],
    groups: dict[str, tuple[str, ...]],
    weapon_augments: dict[str, Any],
) -> None:
    for kind, category, link_field, directory in (
        ("附魔", "附魔技能书", "对应附魔", ENCHANTMENTS_FILE),
        ("宝石", "宝石", "对应宝石", GEMS_FILE),
    ):
        definitions = _require_object(weapon_augments, kind, WEAPON_AUGMENTS_FILE)
        kind_groups = _require_object(
            _require_object(weapon_augments, "分组", WEAPON_AUGMENTS_FILE),
            kind,
            WEAPON_AUGMENTS_FILE,
        )
        for group_id, augment_ids in kind_groups.items():
            if group_id in groups:
                raise GameContentError(f"数据目录有问题：{ITEMS_FILE}：文件名重复 {group_id}.json")
            item_ids: list[str] = []
            file_path = f"{directory}/{group_id}.json"
            for augment_id in augment_ids:
                definition = definitions[str(augment_id)]
                item_id = f"{augment_id}玉简" if kind == "附魔" else str(augment_id)
                item_ids.append(item_id)
                value = {
                    "类别": category,
                    "说明": (
                        f"记载{augment_id}刻法的玉简。"
                        if kind == "附魔"
                        else str(definition["说明"])
                    ),
                    "权重": int(definition["权重"]),
                    "可堆叠": True,
                    link_field: str(augment_id),
                    "评分": int(definition["评分"]),
                    "参考价": int(definition["评分"]) * 2,
                }
                _merge_unique(
                    items,
                    sources,
                    {item_id: value},
                    file_path,
                    "物品",
                )
            groups[str(group_id)] = tuple(item_ids)


def _read_multi_section_catalog(
    reader: JsonDataReader,
    *,
    directory: str,
    sections: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    result = {section: {} for section in sections}
    sources = {section: {} for section in sections}
    groups: dict[str, dict[str, tuple[str, ...]]] = {
        section: {} for section in sections
    }
    allowed = {"版本", *sections}
    for file_path, raw in reader.read_directory(directory):
        value = _object(raw, file_path)
        _require_version(value, file_path)
        _allow_only(value, file_path, allowed)
        present = [section for section in sections if section in value]
        if not present:
            raise GameContentError(
                f"数据文件有问题：{file_path}：没有可识别的 " + "、".join(sections)
            )
        for section in present:
            values = _require_object(value, section, file_path)
            group_id = file_path.rsplit("/", 1)[-1].removesuffix(".json")
            groups[section][group_id] = tuple(str(key) for key in values)
            _merge_unique(
                result[section],
                sources[section],
                values,
                file_path,
                section,
            )
    result["分组"] = groups
    return result


def _read_grouped_catalog(
    reader: JsonDataReader,
    *,
    directory: str,
    section: str,
) -> dict[str, Any]:
    definitions: dict[str, Any] = {}
    sources: dict[str, str] = {}
    groups: dict[str, tuple[str, ...]] = {}
    for file_path, raw in reader.read_directory(directory):
        value = _object(raw, file_path)
        _require_version(value, file_path)
        _allow_only(value, file_path, {"版本", section})
        values = _require_object(value, section, file_path)
        if not values:
            raise GameContentError(f"数据文件有问题：{file_path} -> {section}：资源池不能为空")
        group_id = file_path.rsplit("/", 1)[-1].removesuffix(".json")
        if group_id in groups:
            raise GameContentError(f"数据目录有问题：{directory}：文件名重复 {group_id}.json")
        groups[group_id] = tuple(str(key) for key in values)
        _merge_unique(
            definitions,
            sources,
            values,
            file_path,
            section,
        )
    return {"版本": "目录展开", section: definitions, "分组": groups}


def _read_enemy_catalog(reader: JsonDataReader) -> dict[str, Any]:
    """把敌对修士和灵兽汇入统一参战对象表，同时保留资源分支。"""

    definitions: dict[str, Any] = {}
    sources: dict[str, str] = {}
    groups: dict[str, tuple[str, ...]] = {}
    group_kinds: dict[str, str] = {}
    catalogs = (
        (
            "敌对修士",
            _read_grouped_catalog(
                reader,
                directory=HOSTILE_CULTIVATORS_FILE,
                section="敌对修士",
            ),
        ),
        (
            "灵兽",
            _read_grouped_catalog(
                reader,
                directory=BEASTS_FILE,
                section="灵兽",
            ),
        ),
    )
    for section, catalog in catalogs:
        for group_id, object_ids in catalog["分组"].items():
            if group_id in groups:
                raise GameContentError(f"数据目录有问题：战斗资源文件名重复 {group_id}.json")
            groups[group_id] = tuple(object_ids)
            group_kinds[group_id] = section
        _merge_unique(
            definitions,
            sources,
            catalog[section],
            HOSTILE_CULTIVATORS_FILE if section == "敌对修士" else BEASTS_FILE,
            section,
        )
    return {
        "版本": "目录展开",
        "敌人": definitions,
        "分组": groups,
        "分组类别": group_kinds,
    }


def _merge_unique(
    target: dict[str, Any],
    sources: dict[str, str],
    values: dict[str, Any],
    file_path: str,
    section: str,
) -> None:
    for raw_key, value in values.items():
        key = str(raw_key)
        if key in target:
            raise GameContentError(
                f"数据文件有问题：{file_path} -> {section}.{key}：与 {sources[key]} 重名"
            )
        target[key] = value
        sources[key] = file_path


def _expand_groups(
    group_ids: list[str],
    definitions: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    result: list[str] = []
    for group_id in group_ids:
        result.extend(definitions[str(group_id)])
    return tuple(dict.fromkeys(result))


def _weighted_choice(
    object_ids: tuple[str, ...],
    definitions: dict[str, dict[str, Any]],
    rng: Any,
    kind: str,
) -> str:
    if not object_ids:
        raise GameContentError(f"{kind}整合池不能为空")
    weights = [int(definitions[object_id]["权重"]) for object_id in object_ids]
    return str(rarity_weighted_choice(rng, object_ids, weights))


def _require_version(value: dict[str, Any], path: str) -> None:
    if not str(value.get("版本") or "").strip():
        raise GameContentError(f"数据文件有问题：{path} -> 版本：不能为空")


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GameContentError(f"数据文件有问题：{path}：必须是对象")
    return value


def _require_object(value: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    if key not in value:
        raise GameContentError(f"数据文件有问题：{path} -> {key}：缺少字段")
    return _object(value[key], f"{path} -> {key}")


def _string_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise GameContentError(f"数据文件有问题：{path}：必须是字符串数组")
    result = [item.strip() for item in value]
    if len(result) != len(set(result)):
        raise GameContentError(f"数据文件有问题：{path}：不能重复")
    return result


def _allow_only(value: dict[str, Any], path: str, allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise GameContentError(f"数据文件有问题：{path}：不认识字段 " + "、".join(unknown))


def _attribute(value: Any, path: str, definitions: dict[str, Any]) -> str:
    key = str(value or "").strip()
    if key not in definitions:
        raise GameContentError(f"数据文件有问题：{path}：未登记属性 {key or '<空>'}")
    return key


def _attribute_amount(key: Any, value: Any, definitions: dict[str, Any], path: str) -> float:
    attribute = _attribute(key, path, definitions)
    definition = _object(definitions[attribute], f"{ATTRIBUTES_FILE} -> 属性.{attribute}")
    return _number(value, path, minimum=float(definition["最低值"]), maximum=float(definition["最高值"]))


def _number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GameContentError(f"数据文件有问题：{path}：必须是数字")
    result = float(value)
    if minimum is not None and result < minimum:
        raise GameContentError(f"数据文件有问题：{path}：不能小于 {minimum}")
    if maximum is not None and result > maximum:
        raise GameContentError(f"数据文件有问题：{path}：不能大于 {maximum}")
    return result


def _positive(value: Any, path: str) -> float:
    return _number(value, path, minimum=0.0000001)


def _integer(
    value: Any,
    path: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GameContentError(f"数据文件有问题：{path}：必须是整数")
    if minimum is not None and value < minimum:
        raise GameContentError(f"数据文件有问题：{path}：不能小于 {minimum}")
    if maximum is not None and value > maximum:
        raise GameContentError(f"数据文件有问题：{path}：不能大于 {maximum}")
    return value


def _coordinate(value: Any, path: str) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise GameContentError(f"数据文件有问题：{path}：必须是 [横坐标, 纵坐标]")
    return _integer(value[0], f"{path}[0]"), _integer(value[1], f"{path}[1]")


def _range(value: Any, path: str, *, minimum: int | None = 0) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise GameContentError(f"数据文件有问题：{path}：必须是 [最小值, 最大值]")
    low = _integer(value[0], f"{path}[0]", minimum=minimum)
    high = _integer(value[1], f"{path}[1]", minimum=minimum)
    if high < low:
        raise GameContentError(f"数据文件有问题：{path}：最大值不能小于最小值")
    return low, high


__all__ = ["GameContent", "GameContentError"]
