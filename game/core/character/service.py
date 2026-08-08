"""由角色 JSON 驱动的玩家创建与初始状态服务。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from game.core.data import JsonDataError, JsonDataService, materialize
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.location import LocationService
from game.core.player_state import PlayerStateService

from .contracts import (
    CharacterAlreadyExistsError,
    CharacterCreateCommand,
    CharacterCreationResult,
    CharacterInputError,
    CharacterNotFoundError,
    CharacterProfile,
    CharacterPublicProfile,
    CharacterStateError,
    CharacterStatus,
    EquippedContent,
    InventorySummary,
    WeaponProfile,
)


class CharacterService:
    """拥有玩家角色状态写权限的唯一核心服务。"""

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        player_state: PlayerStateService,
        location: LocationService,
    ) -> None:
        self._data = data
        self._database = database
        self._player_state = player_state
        self._location = location
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
        if not self._player_state.status().initialized:
            raise RuntimeError("人物状态服务必须先于角色服务启动")
        if not self._location.status().initialized:
            raise RuntimeError("玩家位置服务必须先于角色服务启动")

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
            role_name=str(self._role_rule.get("角色类型") or "")
            if self._initialized
            else "",
            gender_count=len(self._gender_values),
            initial_item_count=len(initial_items),
        )

    async def profile(self, user_id: str) -> CharacterProfile:
        """读取一个人物的完整角色事实，不补造缺失状态。"""

        self._require_initialized()
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id 不能为空")
        snapshots = await self._database.list_for_user(normalized_user_id)
        states = {
            (snapshot.address.state_type, snapshot.address.state_key): snapshot.value
            for snapshot in snapshots
        }
        character = states.get(("character", "main"))
        if character is None:
            raise CharacterNotFoundError("尚未创建人物")
        cultivation = states.get(("cultivation", "main"))
        weapon = states.get(("weapon", "main"))
        if cultivation is None or weapon is None:
            raise CharacterStateError("人物资产不完整：缺少修行槽或本命武器")

        realm_id = _state_text(character.get("境界"), "人物.境界")
        realm_name = _state_text(
            self._data.entity("境界", realm_id).get("名称"),
            f"境界 {realm_id}.名称",
        )
        cultivation_slots, equipped_content = self._cultivation_profile(cultivation)
        weapon_profile = self._weapon_profile(weapon)
        inventory = _inventory_summary(states)
        return CharacterProfile(
            user_id=normalized_user_id,
            name=_state_text(character.get("姓名"), "人物.姓名"),
            gender=_state_text(character.get("性别"), "人物.性别"),
            character_type=_state_text(character.get("角色类型"), "人物.角色类型"),
            realm_id=realm_id,
            realm_name=realm_name,
            level=_state_positive_int(character.get("等级"), "人物.等级"),
            experience=_state_nonnegative_int(character.get("经验"), "人物.经验"),
            spirit_stones=_state_nonnegative_int(character.get("灵石"), "人物.灵石"),
            automatic_medicine=_state_bool(character.get("自动用药"), "人物.自动用药"),
            attributes=_state_numbers(character.get("属性"), "人物.属性"),
            resources=_state_numbers(character.get("资源"), "人物.资源"),
            cultivation_slots=cultivation_slots,
            equipped_content=equipped_content,
            weapon=weapon_profile,
            inventory=inventory,
        )

    async def public_profiles(
        self, user_ids: tuple[str, ...]
    ) -> tuple[CharacterPublicProfile, ...]:
        """批量读取附近展示所需的人物公开摘要。"""

        self._require_initialized()
        normalized = _user_ids(user_ids)
        snapshots = await self._database.get_many(
            tuple(StateAddress(user_id, "character", "main") for user_id in normalized)
        )
        by_user = {snapshot.address.user_id: snapshot.value for snapshot in snapshots}
        result: list[CharacterPublicProfile] = []
        for user_id in normalized:
            value = by_user.get(user_id)
            if value is None:
                continue
            realm_id = _state_text(value.get("境界"), "人物.境界")
            realm_name = _state_text(
                self._data.entity("境界", realm_id).get("名称"),
                f"境界 {realm_id}.名称",
            )
            result.append(
                CharacterPublicProfile(
                    user_id=user_id,
                    name=_state_text(value.get("姓名"), "人物.姓名"),
                    gender=_state_text(value.get("性别"), "人物.性别"),
                    realm_id=realm_id,
                    realm_name=realm_name,
                    level=_state_positive_int(value.get("等级"), "人物.等级"),
                )
            )
        return tuple(result)

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
        operations = [
            StateMutation(command.user_id, "character", "main", character_state, 0),
            StateMutation(command.user_id, "cultivation", "main", cultivation_state, 0),
            StateMutation(command.user_id, "weapon", "main", weapon_state, 0),
            self._player_state.initial_mutation(command.user_id),
            self._location.initial_mutation(command.user_id, command.birth_xy),
        ]
        for item_id, grade, quantity in item_rows:
            operations.append(
                StateMutation(
                    command.user_id,
                    "inventory",
                    f"{item_id}:{grade}",
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
                    operations=tuple(operations),
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
        _number(self._weapon_rule.get("基础攻击"), "本命武器.基础攻击")
        _number(self._weapon_rule.get("每级攻击"), "本命武器.每级攻击")

    def _cultivation_profile(
        self, cultivation: Mapping[str, object]
    ) -> tuple[tuple[tuple[str, int], ...], tuple[EquippedContent, ...]]:
        slot_counts: list[tuple[str, int]] = []
        equipped: list[EquippedContent] = []
        for category in ("功法", "真意", "气机"):
            raw_slots = cultivation.get(category)
            if not isinstance(raw_slots, Sequence) or isinstance(
                raw_slots, (str, bytes)
            ):
                raise CharacterStateError(f"修行槽.{category}必须是数组")
            slot_counts.append((category, len(raw_slots)))
            for slot, raw in enumerate(raw_slots, start=1):
                if raw is None:
                    continue
                entry = _state_mapping(raw, f"修行槽.{category}[{slot}]")
                content_id = _state_text(
                    entry.get("编号"), f"修行槽.{category}[{slot}].编号"
                )
                grade = _state_text(
                    entry.get("品级"), f"修行槽.{category}[{slot}].品级"
                )
                name = _state_text(
                    self._data.entity(category, content_id).get("名称"),
                    f"{category} {content_id}.名称",
                )
                equipped.append(
                    EquippedContent(category, slot, content_id, name, grade)
                )
        return tuple(slot_counts), tuple(equipped)

    def _weapon_profile(self, weapon: Mapping[str, object]) -> WeaponProfile:
        level = _state_positive_int(weapon.get("等级"), "本命武器.等级")
        stage = _stage_for_level(self._weapon_stage_rule, level)
        stage_name = _state_text(stage.get("名称"), "器则.器阶.名称")
        stored_stage = _state_text(weapon.get("器阶"), "本命武器.器阶")
        if stored_stage != stage_name:
            raise CharacterStateError(
                f"本命武器器阶与等级不符：{stored_stage} != {stage_name}"
            )
        open_slots = _state_nonnegative_int(
            stage.get("开放器律孔"), "器则.器阶.开放器律孔"
        )
        raw_laws = weapon.get("器律")
        if not isinstance(raw_laws, Sequence) or isinstance(raw_laws, (str, bytes)):
            raise CharacterStateError("本命武器.器律必须是编号数组")
        if len(raw_laws) > open_slots:
            raise CharacterStateError("本命武器已装器律超过当前开放孔数")
        equipped_laws: list[EquippedContent] = []
        for slot, raw in enumerate(raw_laws, start=1):
            content_id = _state_text(raw, f"本命武器.器律[{slot}]")
            name = _state_text(
                self._data.entity("器律", content_id).get("名称"),
                f"器律 {content_id}.名称",
            )
            equipped_laws.append(EquippedContent("器律", slot, content_id, name))
        return WeaponProfile(
            name=_state_text(weapon.get("名称"), "本命武器.名称"),
            level=level,
            experience=_state_nonnegative_int(weapon.get("经验"), "本命武器.经验"),
            attack=(
                _number(self._weapon_rule.get("基础攻击"), "本命武器.基础攻击")
                + _number(self._weapon_rule.get("每级攻击"), "本命武器.每级攻击")
                * (level - 1)
            ),
            stage=stage_name,
            open_law_slots=open_slots,
            equipped_laws=tuple(equipped_laws),
        )

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
            raise CharacterInputError(
                f"姓名长度必须在 {minimum} 到 {maximum} 个字符之间"
            )
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
        }

    def _cultivation_state(self) -> dict[str, object]:
        slots = _mapping(self._role_rule.get("修行槽位"), "人物.json.修行槽位")
        return {
            category: [None] * _positive_int(slots.get(category), f"{category}槽位")
            for category in ("功法", "真意", "气机")
        }

    def _weapon_state(self, creation: Mapping[str, object]) -> dict[str, object]:
        weapon_creation = _mapping(
            creation.get("初始本命武器"), "人物.json.创建.初始本命武器"
        )
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


def _state_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CharacterStateError(f"{label}必须是对象")
    return value


def _state_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CharacterStateError(f"{label}必须是非空字符串")
    return value.strip()


def _state_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CharacterStateError(f"{label}必须是正整数")
    return value


def _state_nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CharacterStateError(f"{label}必须是非负整数")
    return value


def _state_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise CharacterStateError(f"{label}必须是布尔值")
    return value


def _user_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(str(value or "").strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError("user_id不能为空")
    if normalized != values:
        raise ValueError("user_id不能带首尾空白")
    if len(normalized) != len(set(normalized)):
        raise ValueError("user_id不能重复")
    return normalized


def _state_numbers(value: object, label: str) -> tuple[tuple[str, int | float], ...]:
    fields = _state_mapping(value, label)
    result: list[tuple[str, int | float]] = []
    for name, raw in fields.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise CharacterStateError(f"{label}.{name}必须是数值")
        result.append((str(name), raw))
    return tuple(result)


def _inventory_summary(
    states: Mapping[tuple[str, str], Mapping[str, object]],
) -> InventorySummary:
    quantities = tuple(
        _state_positive_int(value.get("数量"), f"背包.{state_key}.数量")
        for (state_type, state_key), value in states.items()
        if state_type == "inventory"
    )
    return InventorySummary(len(quantities), sum(quantities))


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
        item_id = str(entry.get("编号") or "").strip()
        grade = str(entry.get("品级") or "").strip()
        quantity = entry.get("数量")
        if (
            not item_id
            or not grade
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < 1
        ):
            raise JsonDataError(f"人物.json.物品[{index}]字段无效")
        result.append((item_id, grade, quantity))
    if len({(item_id, grade) for item_id, grade, _ in result}) != len(result):
        raise JsonDataError("人物.json.物品不能重复同一编号和品级")
    return tuple(result)


def _stage_for_level(rule: Mapping[str, object], level: int) -> Mapping[str, object]:
    stages = rule.get("器阶")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)):
        raise JsonDataError("本命武器.json.器阶必须是字典列表")
    for raw in stages:
        stage = _mapping(raw, "本命武器.json.器阶")
        bounds = stage.get("等级范围")
        if (
            isinstance(bounds, Sequence)
            and len(bounds) == 2
            and bounds[0] <= level <= bounds[1]
        ):
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
