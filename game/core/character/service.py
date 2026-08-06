"""由角色 JSON 驱动的玩家创建与初始状态服务。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from game.core.activity import ActivityService
from game.core.data import JsonDataError, JsonDataService, materialize
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)

from .contracts import (
    CharacterAlreadyExistsError,
    CharacterCreateCommand,
    CharacterCreationResult,
    CharacterInputError,
    CharacterStatus,
)


class CharacterService:
    """拥有玩家角色状态写权限的唯一核心服务。"""

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        activity: ActivityService,
    ) -> None:
        self._data = data
        self._database = database
        self._activity = activity
        self._initialized = False
        self._role_rule: Mapping[str, object] = {}
        self._gender_values: tuple[str, ...] = ()
        self._grade_values: frozenset[str] = frozenset()
        self._weapon_rule: Mapping[str, object] = {}
        self._weapon_stage_rule: Mapping[str, object] = {}
        self._attributes: Mapping[str, object] = {}

    def initialize(self) -> CharacterStatus:
        if self._initialized:
            raise RuntimeError("角色核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于角色服务启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于角色服务启动")
        if not self._activity.status().initialized:
            raise RuntimeError("人物状态服务必须先于角色服务启动")

        role_rules = self._data.dataset("角色规则")
        role_rule = role_rules.get("人物")
        if not isinstance(role_rule, Mapping):
            raise JsonDataError("角色规则缺少人物.json")
        gender_definition = self._data.dataset("角色定义").get("性别")
        if not isinstance(gender_definition, Mapping):
            raise JsonDataError("角色定义缺少性别.json")
        genders = gender_definition.get("取值")
        if not _strings(genders):
            raise JsonDataError("角色定义.性别.取值不能为空")
        grade_rows = self._data.dataset("基础定义").get("品级")
        if not isinstance(grade_rows, Sequence) or isinstance(grade_rows, (str, bytes)):
            raise JsonDataError("基础定义缺少品级.json")
        creation = _mapping(role_rule.get("创建"), "人物.json.创建")
        weapon_creation = _mapping(
            creation.get("初始本命武器"),
            "人物.json.创建.初始本命武器",
        )
        weapon_rule_name = str(weapon_creation.get("规则") or "").strip()
        weapon_rules = self._data.dataset("炼器规则")
        weapon_rule = weapon_rules.get(weapon_rule_name)
        weapon_stage_rule = weapon_rules.get("器则")
        attributes = self._data.dataset("战斗定义").get("属性")
        self._role_rule = role_rule
        self._gender_values = _strings(genders)
        self._grade_values = frozenset(
            str(_mapping(raw, "品级.json").get("编号") or "").strip()
            for raw in grade_rows
        )
        self._weapon_rule = _mapping(weapon_rule, "炼器规则.本命武器")
        self._weapon_stage_rule = _mapping(weapon_stage_rule, "炼器规则.器则")
        self._attributes = _mapping(attributes, "战斗定义.属性")
        self._validate_static_rules()
        self._initialized = True
        initial_items = _initial_items(self._role_rule)
        return CharacterStatus(
            initialized=True,
            role_name=str(self._role_rule.get("角色类型") or ""),
            gender_count=len(self._gender_values),
            initial_item_count=len(initial_items),
        )

    def status(self) -> CharacterStatus:
        initial_items = _initial_items(self._role_rule) if self._initialized else ()
        return CharacterStatus(
            initialized=self._initialized,
            role_name=str(self._role_rule.get("角色类型") or "") if self._initialized else "",
            gender_count=len(self._gender_values),
            initial_item_count=len(initial_items),
        )

    async def create(self, command: CharacterCreateCommand) -> CharacterCreationResult:
        self._require_initialized()
        self._validate_command(command)
        creation = _mapping(self._role_rule.get("创建"), "人物.json.创建")
        realm_id = str(creation.get("初始境界") or "").strip()
        realm = self._data.entity("境界", realm_id)
        realm_name = str(realm.get("名称") or "").strip()
        if not realm_name:
            raise JsonDataError(f"初始境界缺少名称：{realm_id}")
        initial_level = _positive_int(self._role_rule.get("等级"), "人物初始等级")
        if not _in_range(initial_level, realm.get("等级下限"), realm.get("等级上限")):
            raise JsonDataError("初始等级不属于初始境界")

        character_state = self._character_state(command, realm_id)
        cultivation_state = self._cultivation_state()
        weapon_state = self._weapon_state(creation)
        item_rows = _initial_items(self._role_rule)
        mutations = [
            StateMutation("character", "main", character_state, 0),
            StateMutation("cultivation", "main", cultivation_state, 0),
            StateMutation("weapon", "main", weapon_state, 0),
            self._activity.initial_mutation(),
        ]
        for item_id, grade, quantity in item_rows:
            mutations.append(
                StateMutation(
                    "inventory",
                    f"丹药:{item_id}:{grade}",
                    {"编号": item_id, "品级": grade, "数量": quantity},
                    0,
                )
            )
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=command.user_id,
                    request_id=command.request_id,
                    business_type="创建人物",
                    mutations=tuple(mutations),
                    payload={
                        "姓名": command.name,
                        "性别": command.gender,
                        "出生地": list(command.birth_xy),
                        "初始境界": realm_id,
                    },
                )
            )
        except StateConflictError as exc:
            existing = await self._database.get(
                StateAddress(command.user_id, "character", "main")
            )
            if existing is not None:
                raise CharacterAlreadyExistsError("该用户已经创建过人物") from exc
            raise
        return CharacterCreationResult(
            user_id=command.user_id,
            name=command.name,
            gender=command.gender,
            realm_id=realm_id,
            realm_name=realm_name,
            birth_xy=command.birth_xy,
            initial_items=item_rows,
            replayed=receipt.replayed,
        )

    def _validate_static_rules(self) -> None:
        creation = _mapping(self._role_rule.get("创建"), "人物.json.创建")
        name_rule = _mapping(creation.get("姓名"), "人物.json.创建.姓名")
        minimum = _positive_int(name_rule.get("最短长度"), "姓名最短长度")
        maximum = _positive_int(name_rule.get("最长长度"), "姓名最长长度")
        if minimum > maximum:
            raise JsonDataError("人物.json.创建.姓名长度范围无效")
        pattern = str(name_rule.get("匹配") or "")
        if not pattern:
            raise JsonDataError("人物.json.创建.姓名缺少匹配规则")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise JsonDataError("人物.json.创建.姓名匹配规则无效") from exc
        self._data.entity("境界", str(creation.get("初始境界") or ""))
        _mapping(creation.get("初始出生地"), "人物.json.创建.初始出生地")
        _mapping(creation.get("初始本命武器"), "人物.json.创建.初始本命武器")
        _initial_items(self._role_rule)
        for item_id, grade, _ in _initial_items(self._role_rule):
            self._data.entity("物品", item_id)
            if grade not in self._grade_values:
                raise JsonDataError(f"人物初始物品使用未知品级：{item_id} -> {grade}")
        if not self._attributes:
            raise JsonDataError("战斗定义.属性不能为空")

    def _validate_command(self, command: CharacterCreateCommand) -> None:
        if not command.user_id.strip() or not command.request_id.strip():
            raise CharacterInputError("身份和请求编号不能为空")
        if not command.birth_xy or len(command.birth_xy) != 2:
            raise CharacterInputError("出生地坐标无效")
        name = command.name.strip()
        if name != command.name:
            raise CharacterInputError("姓名不能带首尾空白")
        creation = _mapping(self._role_rule.get("创建"), "人物.json.创建")
        name_rule = _mapping(creation.get("姓名"), "人物.json.创建.姓名")
        minimum = int(name_rule["最短长度"])
        maximum = int(name_rule["最长长度"])
        if not minimum <= len(name) <= maximum:
            raise CharacterInputError(f"姓名长度必须在 {minimum} 到 {maximum} 个字符之间")
        pattern = str(name_rule["匹配"])
        if re.fullmatch(pattern, name) is None:
            raise CharacterInputError("姓名只能使用中文、字母或数字")
        if command.gender not in self._gender_values:
            raise CharacterInputError("性别只能从正式定义中选择")

    def _character_state(
        self, command: CharacterCreateCommand, realm_id: str
    ) -> dict[str, object]:
        overrides = _mapping(self._role_rule.get("属性覆盖"), "人物.json.属性覆盖")
        attributes: dict[str, object] = {
            name: _mapping(raw, f"属性.{name}").get("默认值")
            for name, raw in self._attributes.items()
        }
        attributes.update(materialize(overrides))
        blood = _number(attributes.get("血气上限"), "血气上限")
        spirit = _number(attributes.get("精神上限"), "精神上限")
        return {
            "姓名": command.name,
            "性别": command.gender,
            "角色类型": str(self._role_rule.get("角色类型") or "修士"),
            "境界": realm_id,
            "等级": _positive_int(self._role_rule.get("等级"), "人物初始等级"),
            "经验": int(self._role_rule.get("经验") or 0),
            "灵石": int(self._role_rule.get("灵石") or 0),
            "属性": attributes,
            "属性加成": {},
            "资源": {"血气": blood, "精神": spirit, "护盾": 0},
            "自动用药": bool(self._role_rule.get("自动用药")),
            "位置": {"xy": list(command.birth_xy)},
        }

    def _cultivation_state(self) -> dict[str, object]:
        slots = _mapping(self._role_rule.get("修行槽位"), "人物.json.修行槽位")
        return {
            category: [None] * _positive_int(slots.get(category), f"{category}槽位")
            for category in ("功法", "真意", "气机")
        }

    def _weapon_state(self, creation: Mapping[str, object]) -> dict[str, object]:
        weapon_creation = _mapping(creation.get("初始本命武器"), "人物.json.创建.初始本命武器")
        level = _positive_int(self._weapon_rule.get("初始等级"), "本命武器初始等级")
        stage = _stage_for_level(self._weapon_stage_rule, level)
        return {
            "名称": str(weapon_creation.get("名称") or "无名器胚"),
            "等级": level,
            "经验": 0,
            "器阶": str(stage.get("名称") or "凡器"),
            "器律": [],
        }

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("角色核心微服务尚未初始化")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JsonDataError(f"{label}必须是数值")
    return value


def _initial_items(role_rule: Mapping[str, object]) -> tuple[tuple[str, str, int], ...]:
    raw_items = role_rule.get("物品")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        raise JsonDataError("人物.json.物品必须是字典列表")
    result: list[tuple[str, str, int]] = []
    for index, raw in enumerate(raw_items):
        entry = _mapping(raw, f"人物.json.物品[{index}]")
        identity = str(entry.get("编号") or "").strip()
        grade = str(entry.get("品级") or "").strip()
        quantity = entry.get("数量")
        if not identity or not grade or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise JsonDataError(f"人物.json.物品[{index}]字段无效")
        result.append((identity, grade, quantity))
    if len({(identity, grade) for identity, grade, _ in result}) != len(result):
        raise JsonDataError("人物.json.物品不能重复同一编号和品级")
    return tuple(result)


def _stage_for_level(rule: Mapping[str, object], level: int) -> Mapping[str, object]:
    stages = rule.get("器阶")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)):
        raise JsonDataError("本命武器.json.器阶必须是字典列表")
    for raw in stages:
        stage = _mapping(raw, "本命武器.json.器阶")
        bounds = stage.get("等级范围")
        if isinstance(bounds, Sequence) and len(bounds) == 2 and bounds[0] <= level <= bounds[1]:
            return stage
    raise JsonDataError(f"本命武器等级没有对应器阶：{level}")


def _in_range(value: int, lower: object, upper: object) -> bool:
    return (
        isinstance(lower, int)
        and not isinstance(lower, bool)
        and isinstance(upper, int)
        and not isinstance(upper, bool)
        and lower <= value <= upper
    )


__all__ = ["CharacterService"]
