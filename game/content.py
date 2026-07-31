"""把现行 JSON 目录投影为游戏运行期的只读内容视图。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from game.content_loading import GameDataLoadError, GameDataLoader
from game.core import JsonDataReader, content_section, inverse_weighted_choice
from game.rules.battle.catalog import BattleReportCatalog
from game.rules.battle.foundation import load_battle_foundation


class GameContentError(ValueError):
    """正式 JSON 未满足游戏运行要求。"""


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
    npcs: dict[str, Any]
    enemies: dict[str, Any]
    world: dict[str, Any]

    @classmethod
    def load(cls, reader: JsonDataReader) -> "GameContent":
        try:
            loaded = GameDataLoader(reader).load()
            loaded.require_valid()
            combat = load_battle_foundation(reader.root)
            combat["组合规则"] = reader.read("规则/战斗/构筑.json")
            report = BattleReportCatalog.from_mapping(reader.read("展示/战报.json"))
        except (GameDataLoadError, OSError, TypeError, ValueError) as exc:
            raise GameContentError(str(exc)) from exc

        attributes = reader.read("定义/战斗/属性.json")
        attribute_defaults = {
            str(name): float(definition["默认值"])
            for name, definition in attributes.items()
        }
        initial = reader.read("规则/初始/人物.json")
        cultivation = reader.read("规则/成长/修士.json")
        weapon = reader.read("规则/成长/本命武器.json")
        partner = reader.read("规则/道侣.json")
        player_attributes = {**attribute_defaults, **dict(initial.get("属性覆盖") or {})}
        initial_items = {
            str(value["编号"]): int(value["数量"])
            for value in initial.get("物品") or ()
        }
        player_rules = {
            "人物": {
                "初始等级": int(initial["等级"]),
                "初始灵石": int(initial["灵石"]),
                "属性": player_attributes,
                "等级上限": int(cultivation["等级上限"]),
                "突破间隔": int(cultivation["突破间隔"]),
                "每级成长": dict(cultivation["属性成长"]["每级"]),
                "经验": dict(cultivation["经验"]),
            },
            "本命武器": dict(weapon),
            "道侣": {
                **dict(partner),
                **{
                    f"{kind}位": int(count)
                    for kind, count in dict(partner["同行构筑"]).items()
                },
            },
            "初始物品": initial_items,
        }

        grades = {
            str(value["编号"]): dict(value)
            for value in reader.read("定义/品级.json")
        }
        groups = loaded.groups
        technique_groups = _groups_for(groups, "功法")
        enchantment_groups = _groups_for(groups, "附魔")
        gem_groups = _groups_for(groups, "宝石")
        item_groups = _groups_for(groups, "物品")
        npc_groups = _groups_for(groups, "道侣")
        enemy_groups = _groups_for(groups, "敌人")

        npc_definitions = {
            identity: _character_definition(value, attribute_defaults, cultivation)
            for identity, value in loaded.entities["道侣"].items()
        }
        enemy_definitions: dict[str, dict[str, Any]] = {}
        regions: dict[str, dict[str, Any]] = {}
        locations: dict[str, dict[str, Any]] = {}
        world_definition: dict[str, Any] | None = None
        for document in loaded.catalog.documents:
            section = content_section(document)
            if section == "敌人":
                enemy_definitions.update(
                    {
                        str(name): _character_definition(value, attribute_defaults, cultivation)
                        for name, value in document.value.items()
                    }
                )
            elif section == "区域":
                value = dict(document.value)
                regions[str(value.get("名称") or document.file_id)] = value
            elif section == "地点":
                value = dict(document.value)
                locations[str(value.get("名称") or document.file_id)] = value
            elif section == "世界":
                world_definition = dict(document.value)
        if world_definition is None:
            raise GameContentError("正式内容缺少世界定义")

        item_definitions = {
            identity: dict(value)
            for identity, value in loaded.entities["物品"].items()
        }
        return cls(
            player=player_rules,
            activities={
                "闭关": reader.read("规则/修行/闭关.json"),
                "探险": reader.read("规则/修行/探险.json"),
            },
            grades={"品级": grades},
            combat=combat,
            battle_report=report,
            techniques={
                "功法": {key: dict(value) for key, value in loaded.entities["功法"].items()},
                "分组": technique_groups,
            },
            items={
                "物品": item_definitions,
                "分组": item_groups,
                "物品类别": tuple(dict.fromkeys(str(value["类别"]) for value in item_definitions.values())),
            },
            weapon_augments={
                "附魔": {key: dict(value) for key, value in loaded.entities["附魔"].items()},
                "宝石": {key: dict(value) for key, value in loaded.entities["宝石"].items()},
                "分组": {"附魔": enchantment_groups, "宝石": gem_groups},
            },
            npcs={"道侣": npc_definitions, "分组": npc_groups},
            enemies={
                "敌人": enemy_definitions,
                "分组": enemy_groups,
                "分组类别": {
                    group: str(enemy_definitions[identities[0]].get("角色类型") or "灵兽")
                    for group, identities in enemy_groups.items()
                    if identities
                },
            },
            world={"世界": world_definition, "区域": regions, "地点": locations},
        )

    @property
    def technique_definitions(self):
        return self.techniques["功法"]

    @property
    def technique_groups(self):
        return self.techniques["分组"]

    @property
    def enchantment_groups(self):
        return self.weapon_augments["分组"]["附魔"]

    @property
    def gem_groups(self):
        return self.weapon_augments["分组"]["宝石"]

    @property
    def combination_rules(self):
        return self.combat["组合规则"]

    @property
    def grade_definitions(self):
        return self.grades["品级"]

    @property
    def attribute_definitions(self):
        return self.combat["属性"]

    @property
    def mechanism_definitions(self):
        return self.combat["机制"]

    @property
    def atomic_ability_definitions(self):
        return self.combat["原子能力"]

    @property
    def event_definitions(self):
        return tuple(self.combat["事件"])

    @property
    def item_definitions(self):
        return self.items["物品"]

    @property
    def enchantment_definitions(self):
        return self.weapon_augments["附魔"]

    @property
    def gem_definitions(self):
        return self.weapon_augments["宝石"]

    @property
    def item_groups(self):
        return self.items["分组"]

    @property
    def item_categories(self):
        return tuple(self.items["物品类别"])

    @property
    def npc_definitions(self):
        return self.npcs["道侣"]

    @property
    def npc_groups(self):
        return self.npcs["分组"]

    @property
    def npc_home_locations(self):
        result = {}
        for location_id, definition in self.location_definitions.items():
            for npc_id in self.npcs_in_groups(list(definition.get("道侣池") or ())):
                result[npc_id] = location_id
        return result

    @property
    def enemy_definitions(self):
        return self.enemies["敌人"]

    @property
    def enemy_groups(self):
        return self.enemies["分组"]

    @property
    def enemy_group_kinds(self):
        return self.enemies["分组类别"]

    @property
    def world_definition(self):
        return self.world["世界"]

    @property
    def location_definitions(self):
        return self.world["地点"]

    @property
    def region_definitions(self):
        return self.world["区域"]

    def npcs_in_groups(self, groups):
        return _expand_groups(groups, self.npc_groups)

    def items_in_groups(self, groups):
        return _expand_groups(groups, self.item_groups)

    def enemies_in_groups(self, groups):
        return _expand_groups(groups, self.enemy_groups)

    def techniques_in_groups(self, groups):
        return _expand_groups(groups, self.technique_groups)

    def enchantments_in_groups(self, groups):
        return _expand_groups(groups, self.enchantment_groups)

    def gems_in_groups(self, groups):
        return _expand_groups(groups, self.gem_groups)

    def choose_npc(self, values, rng):
        return _choose(values, self.npc_definitions, rng)

    def choose_enemy(self, values, rng):
        return _choose(values, self.enemy_definitions, rng)

    def choose_item(self, values, rng):
        return _choose(values, self.item_definitions, rng)

    def choose_technique(self, values, rng):
        return _choose(values, self.technique_definitions, rng)

    def choose_enchantment(self, values, rng):
        return _choose(values, self.enchantment_definitions, rng)

    def choose_gem(self, values, rng):
        return _choose(values, self.gem_definitions, rng)

    def choose_grade(self, rng):
        return _choose(tuple(self.grade_definitions), self.grade_definitions, rng)

    def grade_at_least(self, grade_id: str, minimum_grade_id: str) -> bool:
        return int(self.grade_definitions[str(grade_id)]["阶序"]) >= int(
            self.grade_definitions[str(minimum_grade_id)]["阶序"]
        )

    def item_price(self, item_id: str, grade_id: str) -> int:
        item = self.item_definitions[str(item_id)]
        grade = self.grade_definitions[str(grade_id)]
        return max(0, int(float(item["参考价"]) * float(grade["价格系数"]) + 0.5))

    def graded_item_definition(self, item_id: str, grade_id: str) -> dict[str, Any]:
        item = dict(self.item_definitions[str(item_id)])
        grade = self.grade_definitions[str(grade_id)]
        multiplier = float(grade["能力倍率"])
        use = item.get("使用效果")
        if isinstance(use, Mapping):
            scaled = dict(use)
            for field in ("恢复量", "经验"):
                if field in scaled:
                    scaled[field] = max(1, int(float(scaled[field]) * multiplier + 0.5))
            item["使用效果"] = scaled
        item.update(
            {
                "基础物品": str(item_id),
                "名称": f"{grade['名称']}·{item['名称']}",
                "品级": str(grade_id),
                "能力倍率": multiplier,
                "参考价": self.item_price(item_id, grade_id),
            }
        )
        return item

    def combat_item_definitions(self) -> dict[str, dict[str, Any]]:
        result = {key: dict(value) for key, value in self.item_definitions.items()}
        for item_id in self.item_definitions:
            for grade_id in self.grade_definitions:
                value = self.graded_item_definition(item_id, grade_id)
                result[f"{grade_id}:{item_id}"] = value
        return result

    def configured_weapon_augment(self, kind, augment_id, grade_id, *, instance_id):
        definitions = {"附魔": self.enchantment_definitions, "宝石": self.gem_definitions}
        definition = definitions[str(kind)][str(augment_id)]
        return {
            "实例": str(instance_id),
            "类型": str(kind),
            "编号": str(augment_id),
            "名称": str(definition["名称"]),
            "品级": str(grade_id),
            "威力倍率": float(self.grade_definitions[str(grade_id)]["能力倍率"]),
            "能力": [dict(value) for value in definition["能力"]],
        }

    def configured_battle_techniques(self, definitions, *, instance_prefix):
        result = []
        for index, value in enumerate(definitions, start=1):
            identity = str(value["编号"])
            grade_id = str(value["品级"])
            definition = self.technique_definitions[identity]
            result.append(
                {
                    "实例": f"{instance_prefix}:{index}",
                    "编号": identity,
                    "名称": str(definition["名称"]),
                    "品级": grade_id,
                    "出生序号": index,
                    "威力倍率": float(self.grade_definitions[grade_id]["能力倍率"]),
                    "能力": [dict(node) for node in definition["能力"]],
                }
            )
        return result

    def attributes_at_level(self, attributes, growth, level):
        result = {str(key): float(value) for key, value in attributes.items()}
        for key, amount in growth.items():
            result[str(key)] = result.get(str(key), 0.0) + max(0, int(level) - 1) * float(amount)
        return result

    def ability_executor(self, node):
        ability = str(node.get("能力") or "")
        try:
            return str(self.atomic_ability_definitions[ability]["执行器"])
        except KeyError as exc:
            raise GameContentError(f"未知原子能力：{ability or '<空>'}") from exc


def _groups_for(groups: Mapping[str, Mapping[str, Sequence[str]]], section: str):
    return {
        str(file_id): tuple(str(value) for value in sections[section])
        for file_id, sections in groups.items()
        if section in sections
    }


def _expand_groups(groups: Sequence[str], definitions: Mapping[str, Sequence[str]]):
    result = []
    for group in groups:
        key = str(group).removesuffix(".json")
        if key not in definitions:
            raise GameContentError(f"资源池不存在：{key}")
        result.extend(str(value) for value in definitions[key])
    return tuple(result)


def _choose(values: Sequence[str], definitions: Mapping[str, Mapping[str, Any]], rng):
    candidates = tuple(str(value) for value in values)
    if not candidates:
        raise GameContentError("候选池不能为空")
    weights = [definitions[value].get("权重") for value in candidates]
    if all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in weights):
        return str(inverse_weighted_choice(rng, candidates, weights))
    return str(rng.choice(candidates))


def _character_definition(value, defaults, cultivation):
    result = dict(value)
    result["属性"] = {**defaults, **dict(value.get("属性覆盖") or {})}
    result["每级成长"] = dict(value.get("每级成长") or cultivation["属性成长"]["每级"])
    return result


__all__ = ["GameContent", "GameContentError"]
