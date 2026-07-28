"""运行期中文配置的统一加载与跨文件校验。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from game.core import JsonDataReader
from game.rules.battle.catalog import BattleReportCatalog
from game.rules.battle.executors import EXECUTOR_CATEGORIES
from game.rules.battle.schema import RuleSchemaError, RuleSchemaValidator


PLAYER_FILE = "rules/人物/人物.json"
ACTIVITIES_FILE = "rules/修炼/修炼.json"
ATTRIBUTES_FILE = "rules/战斗/属性.json"
RESOURCES_FILE = "rules/战斗/资源.json"
COMBAT_FLOW_FILE = "rules/战斗/流程.json"
ATOMIC_ABILITIES_FILE = "rules/战斗/原子能力.json"
BATTLE_REPORT_FILE = "rules/战斗/战报.json"
TECHNIQUES_FILE = "content/功法"
COMBAT_CONTENT_FILE = "content/战斗机制"
MECHANISMS_FILE = COMBAT_CONTENT_FILE
AFFIXES_FILE = COMBAT_CONTENT_FILE
ITEMS_FILE = "content/物品"
NPCS_FILE = "content/角色"
ENEMIES_FILE = "content/敌人"
WORLD_FILE = "content/世界/青岚山境.json"


class GameContentError(ValueError):
    """运行配置缺字段、引用错误或使用了未知战斗能力。"""


@dataclass(frozen=True)
class GameContent:
    player: dict[str, Any]
    activities: dict[str, Any]
    combat: dict[str, Any]
    battle_report: BattleReportCatalog
    techniques: dict[str, Any]
    items: dict[str, Any]
    npcs: dict[str, Any]
    enemies: dict[str, Any]
    world: dict[str, Any]

    @classmethod
    def load(cls, reader: JsonDataReader) -> "GameContent":
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

        content = cls(
            player=_read_versioned(reader, PLAYER_FILE),
            activities=_read_versioned(reader, ACTIVITIES_FILE),
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
            items=_read_item_catalog(reader),
            npcs=_read_grouped_catalog(
                reader,
                directory=NPCS_FILE,
                section="修士",
            ),
            enemies=_read_grouped_catalog(
                reader,
                directory=ENEMIES_FILE,
                section="敌人",
            ),
            world=_read_versioned(reader, WORLD_FILE),
        )
        _validate(content)
        return content

    @property
    def technique_definitions(self) -> dict[str, dict[str, Any]]:
        return self.techniques["功法"]

    @property
    def rarity_definitions(self) -> dict[str, dict[str, Any]]:
        return self.techniques["品级"]

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
    def item_categories(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.items["物品类别"])

    @property
    def npc_definitions(self) -> dict[str, dict[str, Any]]:
        return self.npcs["修士"]

    @property
    def npc_groups(self) -> dict[str, tuple[str, ...]]:
        return self.npcs["分组"]

    @property
    def enemy_definitions(self) -> dict[str, dict[str, Any]]:
        return self.enemies["敌人"]

    @property
    def enemy_groups(self) -> dict[str, tuple[str, ...]]:
        return self.enemies["分组"]

    @property
    def world_definition(self) -> dict[str, Any]:
        return self.world["世界"]

    @property
    def location_definitions(self) -> dict[str, dict[str, Any]]:
        return self.world["地点"]

    def npcs_in_groups(self, groups: list[str]) -> tuple[str, ...]:
        return _expand_groups(groups, self.npc_groups)

    def enemies_in_groups(self, groups: list[str]) -> tuple[str, ...]:
        return _expand_groups(groups, self.enemy_groups)

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
            rarity_id = str(value["品级"])
            technique = self.technique_definitions[technique_id]
            rarity = self.rarity_definitions[rarity_id]
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
                    "品级": rarity_id,
                    "出生序号": index,
                    "威力倍率": float(rarity["威力倍率"]),
                    "词条": affixes,
                    "能力": [dict(node) for node in technique.get("组成") or ()],
                }
            )
        return result


def _validate(content: GameContent) -> None:
    character = _require_object(content.player, "人物", PLAYER_FILE)
    weapon = _require_object(content.player, "本命武器", PLAYER_FILE)
    seclusion = _require_object(content.activities, "闭关", ACTIVITIES_FILE)
    exploration = _require_object(content.activities, "探险", ACTIVITIES_FILE)
    attributes = _require_object(content.combat, "属性", ATTRIBUTES_FILE)
    affixes = _require_object(content.combat, "词条", AFFIXES_FILE)
    abilities = _require_object(content.combat, "原子能力", ATOMIC_ABILITIES_FILE)
    mechanisms = _require_object(content.combat, "机制", MECHANISMS_FILE)
    techniques = _require_object(content.techniques, "功法", TECHNIQUES_FILE)
    rarities = _require_object(content.techniques, "品级", TECHNIQUES_FILE)
    items = _require_object(content.items, "物品", ITEMS_FILE)
    categories = _string_list(content.items.get("物品类别"), f"{ITEMS_FILE} -> 物品类别")
    npcs = _require_object(content.npcs, "修士", NPCS_FILE)
    enemies = _require_object(content.enemies, "敌人", ENEMIES_FILE)
    world = _require_object(content.world, "世界", WORLD_FILE)
    locations = _require_object(content.world, "地点", WORLD_FILE)

    validator = _validate_combat(content.combat, attributes, affixes, abilities, mechanisms)
    _validate_player(character, weapon, attributes, content.combat)
    _validate_activities(seclusion, exploration)
    _validate_techniques(techniques, rarities, affixes, validator)
    _validate_items(items, categories)
    _validate_npcs(
        npcs,
        items,
        techniques,
        rarities,
        affixes,
        attributes,
        content.combat,
        int(character["等级上限"]),
    )
    _validate_enemies(
        enemies,
        items,
        techniques,
        rarities,
        affixes,
        attributes,
        content.combat,
        int(character["等级上限"]),
    )
    _validate_world(
        world,
        locations,
        content.npc_groups,
        content.enemy_groups,
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
        _positive(value.get("权重"), f"{path}.权重")

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


def _validate_techniques(
    techniques: dict[str, Any],
    rarities: dict[str, Any],
    affixes: dict[str, Any],
    validator: RuleSchemaValidator,
) -> None:
    if not techniques or not rarities:
        raise GameContentError(f"数据文件有问题：{TECHNIQUES_FILE}：功法和品级不能为空")
    maximum_affix_count = 0
    for rarity_id, definition in rarities.items():
        path = f"{TECHNIQUES_FILE} -> 品级.{rarity_id}"
        value = _object(definition, path)
        _positive(value.get("权重"), f"{path}.权重")
        _positive(value.get("威力倍率"), f"{path}.威力倍率")
        count = _integer(value.get("词条数量"), f"{path}.词条数量", minimum=0)
        _integer(value.get("评分"), f"{path}.评分", minimum=0)
        maximum_affix_count = max(maximum_affix_count, count)
        if count > len(affixes):
            raise GameContentError(f"数据文件有问题：{path}.词条数量：不能超过基础词条库数量")

    for technique_id, definition in techniques.items():
        path = f"{TECHNIQUES_FILE} -> 功法.{technique_id}"
        value = _object(definition, path)
        if not str(technique_id).strip():
            raise GameContentError(f"数据文件有问题：{path}：功法名不能为空")
        if not str(value.get("说明") or "").strip():
            raise GameContentError(f"数据文件有问题：{path}.说明：不能为空")
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


def _validate_items(items: dict[str, Any], categories: list[str]) -> None:
    if "功法" not in categories:
        raise GameContentError(f"数据文件有问题：{ITEMS_FILE} -> 物品类别：缺少功法")
    for item_id, definition in items.items():
        path = f"{ITEMS_FILE} -> 物品.{item_id}"
        value = _object(definition, path)
        category = str(value.get("类别") or "")
        if category not in categories or category == "功法":
            raise GameContentError(f"数据文件有问题：{path}.类别：未知或不可用类别 {category}")
        if not str(value.get("说明") or "").strip():
            raise GameContentError(f"数据文件有问题：{path}.说明：不能为空")
        if not isinstance(value.get("可堆叠"), bool):
            raise GameContentError(f"数据文件有问题：{path}.可堆叠：必须是布尔值")
        _integer(value.get("评分"), f"{path}.评分", minimum=0)
        _integer(value.get("参考价"), f"{path}.参考价", minimum=0)
        use = value.get("使用效果")
        if use is not None:
            use_value = _object(use, f"{path}.使用效果")
            if use_value.get("类型") not in {"恢复血气", "恢复精神"}:
                raise GameContentError(f"数据文件有问题：{path}.使用效果.类型：未知物品效果")
            _positive(use_value.get("恢复量"), f"{path}.使用效果.恢复量")


def _validate_npcs(
    npcs: dict[str, Any],
    items: dict[str, Any],
    techniques: dict[str, Any],
    rarities: dict[str, Any],
    affixes: dict[str, Any],
    attribute_definitions: dict[str, Any],
    combat: dict[str, Any],
    maximum_level: int,
) -> None:
    if not npcs:
        raise GameContentError(f"数据文件有问题：{NPCS_FILE} -> 修士：不能为空")
    required = set(
        _string_list(
            combat.get("参战者必需属性"),
            f"{ATTRIBUTES_FILE} -> 参战者必需属性",
        )
    )
    for npc_id, definition in npcs.items():
        path = f"{NPCS_FILE} -> 修士.{npc_id}"
        value = _object(definition, path)
        _allow_only(
            value,
            path,
            {
                "身份",
                "说明",
                "等级",
                "实力波动",
                "属性",
                "本命武器",
                "功法",
                "战斗策略",
                "纳戒",
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
        _level_range(value.get("等级"), f"{path}.等级", maximum_level)
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
        _validate_weapon(value, path)
        _validate_equipped_techniques(value, path, techniques, rarities, affixes)
        _validate_combat_strategy(value, path)
        _validate_item_pool(_require_object(value, "纳戒", path), f"{path}.纳戒", items)


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
    rarities: dict[str, Any],
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
        rarity_id = str(technique.get("品级") or "")
        if technique_id not in techniques:
            raise GameContentError(f"数据文件有问题：{technique_path}.功法：未知功法 {technique_id}")
        if rarity_id not in rarities:
            raise GameContentError(f"数据文件有问题：{technique_path}.品级：未知品级 {rarity_id}")
        configured_affixes = technique.get("词条") or []
        if not isinstance(configured_affixes, list):
            raise GameContentError(f"数据文件有问题：{technique_path}.词条：必须是数组")
        expected = int(rarities[rarity_id]["词条数量"])
        if len(configured_affixes) != expected:
            raise GameContentError(
                f"数据文件有问题：{technique_path}.词条：{rarity_id}必须配置 {expected} 条"
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


def _validate_item_pool(value: dict[str, Any], path: str, items: dict[str, Any]) -> None:
    _allow_only(value, path, {"灵石", "物品"})
    _range(value.get("灵石"), f"{path}.灵石")
    configured_items = value.get("物品") or []
    if not isinstance(configured_items, list):
        raise GameContentError(f"数据文件有问题：{path}.物品：必须是数组")
    for index, raw_item in enumerate(configured_items):
        item_path = f"{path}.物品[{index}]"
        configured = _object(raw_item, item_path)
        _allow_only(configured, item_path, {"物品", "概率", "数量"})
        item_id = str(configured.get("物品") or "")
        if item_id not in items:
            raise GameContentError(f"数据文件有问题：{item_path}.物品：未知物品 {item_id}")
        _number(configured.get("概率"), f"{item_path}.概率", minimum=0, maximum=1)
        _range(configured.get("数量"), f"{item_path}.数量", minimum=1)


def _validate_enemies(
    enemies: dict[str, Any],
    items: dict[str, Any],
    techniques: dict[str, Any],
    rarities: dict[str, Any],
    affixes: dict[str, Any],
    attribute_definitions: dict[str, Any],
    combat: dict[str, Any],
    maximum_level: int,
) -> None:
    if not enemies:
        raise GameContentError(f"数据文件有问题：{ENEMIES_FILE} -> 敌人：不能为空")
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
                "等级",
                "实力波动",
                "属性",
                "每级成长",
                "掉落",
                "本命武器",
                "功法",
                "战斗策略",
                "纳戒",
                "交锋所得",
            },
        )
        for key in ("类别", "说明"):
            if not str(value.get(key) or "").strip():
                raise GameContentError(f"数据文件有问题：{path}.{key}：不能为空")
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
        if str(value["类别"]) == "修士":
            if "每级成长" in value:
                raise GameContentError(
                    f"数据文件有问题：{path}.每级成长：敌对修士必须复用人物每级成长"
                )
            if "掉落" in value:
                raise GameContentError(
                    f"数据文件有问题：{path}.掉落：修士战利品只能来自其剩余纳戒"
                )
            _validate_weapon(value, path)
            _validate_equipped_techniques(value, path, techniques, rarities, affixes)
            _validate_combat_strategy(value, path)
            _validate_item_pool(_require_object(value, "纳戒", path), f"{path}.纳戒", items)
        else:
            forbidden = {"本命武器", "功法", "战斗策略", "纳戒"}.intersection(value)
            if forbidden:
                raise GameContentError(
                    f"数据文件有问题：{path}：{value['类别']}不能配置 "
                    + "、".join(sorted(forbidden))
                )
            growth = _require_object(value, "每级成长", path)
            for key, amount in growth.items():
                _attribute(key, f"{path}.每级成长.{key}", attribute_definitions)
                _number(amount, f"{path}.每级成长.{key}")
            _validate_item_pool(_require_object(value, "掉落", path), f"{path}.掉落", items)
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
    for location_id, definition in locations.items():
        path = f"{WORLD_FILE} -> 地点.{location_id}"
        value = _object(definition, path)
        for key in ("地貌", "说明"):
            if not str(value.get(key) or "").strip():
                raise GameContentError(f"数据文件有问题：{path}.{key}：不能为空")
        functions = _string_list(value.get("可用功能"), f"{path}.可用功能")
        unknown = set(functions) - {"闭关", "探险"}
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
        for group_id in npc_pool:
            if group_id not in npc_groups:
                raise GameContentError(
                    f"数据文件有问题：{path}.修士池：没有角色文件 {group_id}.json"
                )
        enemy_pool = _string_list(value.get("敌人池"), f"{path}.敌人池")
        if "探险" in functions and not enemy_pool:
            raise GameContentError(f"数据文件有问题：{path}.敌人池：探险地点不能为空")
        for group_id in enemy_pool:
            if group_id not in enemy_groups:
                raise GameContentError(
                    f"数据文件有问题：{path}.敌人池：没有敌人文件 {group_id}.json"
                )
    for required in ("闭关", "探险"):
        if required not in available_functions:
            raise GameContentError(f"数据文件有问题：{WORLD_FILE}：没有地点提供{required}")


def _read_versioned(reader: JsonDataReader, path: str) -> dict[str, Any]:
    value = _object(reader.read(path), path)
    _require_version(value, path)
    return value


def _read_technique_catalog(reader: JsonDataReader) -> dict[str, Any]:
    rarities: dict[str, Any] = {}
    techniques: dict[str, Any] = {}
    rarity_sources: dict[str, str] = {}
    technique_sources: dict[str, str] = {}
    for file_path, raw in reader.read_directory(TECHNIQUES_FILE):
        value = _object(raw, file_path)
        _require_version(value, file_path)
        sections = set(value) - {"版本"}
        if not sections or not sections <= {"品级", "功法"}:
            raise GameContentError(
                f"数据文件有问题：{file_path}：功法目录中的文件只能包含品级或功法"
            )
        if "品级" in value:
            _merge_unique(
                rarities,
                rarity_sources,
                _require_object(value, "品级", file_path),
                file_path,
                "品级",
            )
        if "功法" in value:
            _merge_unique(
                techniques,
                technique_sources,
                _require_object(value, "功法", file_path),
                file_path,
                "功法",
            )
    return {"版本": "目录展开", "品级": rarities, "功法": techniques}


def _read_item_catalog(reader: JsonDataReader) -> dict[str, Any]:
    categories: list[str] = []
    items: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for file_path, raw in reader.read_directory(ITEMS_FILE):
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
            _merge_unique(
                items,
                sources,
                _require_object(value, "物品", file_path),
                file_path,
                "物品",
            )
    return {"版本": "目录展开", "物品类别": categories, "物品": items}


def _read_multi_section_catalog(
    reader: JsonDataReader,
    *,
    directory: str,
    sections: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    result = {section: {} for section in sections}
    sources = {section: {} for section in sections}
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
            _merge_unique(
                result[section],
                sources[section],
                _require_object(value, section, file_path),
                file_path,
                section,
            )
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
