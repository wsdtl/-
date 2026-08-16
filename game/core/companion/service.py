"""解释世界道侣定义并管理玩家关系、同行位与轻实例。"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.core.database import DatabaseService, StateAddress, StateMutation

from .contracts import (
    ActiveCompanion,
    CompanionDefinition,
    CompanionDialogue,
    CompanionFarewellError,
    CompanionFarewellPlan,
    CompanionGiftError,
    CompanionGiftPlan,
    CompanionInstance,
    CompanionInvitationError,
    CompanionInvitationPlan,
    CompanionNotFoundError,
    CompanionRelation,
    CompanionReward,
    CompanionRules,
    CompanionStateError,
    CompanionStatus,
    LocalCultivator,
)

RELATION_STATE = "companion_relation"
ACTIVE_STATE = "companion_active"
INSTANCE_STATE = "companion_instance"
ACTIVE_KEY = "main"
_AFFECTION_QUANTUM = Decimal("0.1")


class CompanionService:
    """拥有道侣静态身份和玩家个人道侣状态的核心边界。"""

    state_types = frozenset({RELATION_STATE, ACTIVE_STATE, INSTANCE_STATE})

    def __init__(self, data: JsonDataService, database: DatabaseService) -> None:
        self._data = data
        self._database = database
        self._initialized = False
        self._rules: CompanionRules | None = None
        self._definitions: Mapping[str, CompanionDefinition] = MappingProxyType({})
        self._by_name: Mapping[str, str] = MappingProxyType({})
        self._by_location: Mapping[str, tuple[LocalCultivator, ...]] = MappingProxyType(
            {}
        )

    def initialize(self) -> CompanionStatus:
        if self._initialized:
            raise RuntimeError("道侣核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于道侣核心启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于道侣核心启动")
        self._rules = self._load_rules()
        if self._rules.active_limit != 1:
            raise JsonDataError("当前同行位契约要求道侣.同行上限为1")
        if self._rules.full_reward_lifetime_limit != 1:
            raise JsonDataError("当前回礼契约要求每名道侣终身次数为1")
        realms = self._realms()
        grade_ids = frozenset(
            _text(value.get("编号"), "品级.编号")
            for value in _sequence(
                self._data.dataset("基础定义").get("品级"), "定义/品级.json"
            )
        )
        definitions: dict[str, CompanionDefinition] = {}
        by_name: dict[str, str] = {}
        by_location: dict[str, list[LocalCultivator]] = {}
        for companion_id, value in self._data.entities("道侣").items():
            definition = self._definition(companion_id, value, realms, grade_ids)
            normalized_name = _normalize(definition.name)
            if normalized_name in by_name:
                raise JsonDataError(f"道侣名称重复：{definition.name}")
            definitions[companion_id] = definition
            by_name[normalized_name] = companion_id
            by_location.setdefault(definition.location_name, []).append(
                LocalCultivator(
                    definition.companion_id,
                    definition.name,
                    definition.gender,
                    definition.title,
                    definition.description,
                    definition.realm_id,
                    definition.realm_name,
                    definition.level,
                    definition.interactable,
                )
            )
        self._definitions = MappingProxyType(definitions)
        self._by_name = MappingProxyType(by_name)
        self._by_location = MappingProxyType(
            {
                location: tuple(
                    sorted(values, key=lambda item: (item.name, item.companion_id))
                )
                for location, values in by_location.items()
            }
        )
        self._initialized = True
        return self.status()

    def status(self) -> CompanionStatus:
        return CompanionStatus(
            self._initialized,
            len(self._definitions),
            len(self._by_location),
        )

    def rules(self) -> CompanionRules:
        self._require_initialized()
        if self._rules is None:
            raise CompanionStateError("道侣规则尚未完成初始化")
        return self._rules

    def definition(self, identifier: str) -> CompanionDefinition:
        self._require_initialized()
        query = str(identifier or "").strip()
        companion_id = (
            query
            if query in self._definitions
            else self._by_name.get(_normalize(query))
        )
        if companion_id is None:
            raise CompanionNotFoundError(f"未找到道侣：{query or '<空>'}")
        return self._definitions[companion_id]

    def local_cultivators(
        self,
        location_name: str,
        *,
        exclude_companion_ids: Sequence[str] = (),
    ) -> tuple[LocalCultivator, ...]:
        self._require_initialized()
        normalized = str(location_name or "").strip()
        if not normalized:
            return ()
        excluded = frozenset(
            str(value or "").strip() for value in exclude_companion_ids
        )
        return tuple(
            value
            for value in self._by_location.get(normalized, ())
            if value.companion_id not in excluded
        )

    async def relation(self, user_id: str, companion_id: str) -> CompanionRelation:
        self._require_initialized()
        definition = self.definition(companion_id)
        snapshot = await self._database.get(
            StateAddress(_user_id(user_id), RELATION_STATE, definition.companion_id)
        )
        if snapshot is None:
            return CompanionRelation(
                definition.companion_id,
                Decimal(0),
                MappingProxyType({}),
                "",
                "",
                0,
            )
        value = _state_mapping(snapshot.value, f"{RELATION_STATE}/{companion_id}")
        allowed = {"当前好感", "赠礼累计", "首次圆满时间", "首次邀约时间"}
        if unknown := set(value) - allowed:
            raise CompanionStateError(
                f"道侣关系包含未知字段：{'、'.join(sorted(unknown))}"
            )
        totals_value = _state_mapping(value.get("赠礼累计"), "道侣关系.赠礼累计")
        totals: dict[str, int] = {}
        for key, raw in totals_value.items():
            parts = str(key).split(":")
            if len(parts) != 2 or len(parts[0]) != 6 or len(parts[1]) != 2:
                raise CompanionStateError(f"赠礼累计键无效：{key}")
            totals[str(key)] = _state_positive_int(raw, f"赠礼累计.{key}")
        return CompanionRelation(
            definition.companion_id,
            _state_affection(value.get("当前好感"), "道侣关系.当前好感"),
            MappingProxyType(dict(sorted(totals.items()))),
            _optional_text(value.get("首次圆满时间")),
            _optional_text(value.get("首次邀约时间")),
            snapshot.version,
        )

    async def active(self, user_id: str) -> ActiveCompanion | None:
        self._require_initialized()
        snapshot = await self._database.get(
            StateAddress(_user_id(user_id), ACTIVE_STATE, ACTIVE_KEY)
        )
        if snapshot is None:
            return None
        value = _state_mapping(snapshot.value, f"{ACTIVE_STATE}/{ACTIVE_KEY}")
        if set(value) != {"道侣编号"}:
            raise CompanionStateError("同行道侣状态必须只保存道侣编号")
        companion_id = _state_text(value.get("道侣编号"), "同行道侣.道侣编号")
        self.definition(companion_id)
        return ActiveCompanion(companion_id, snapshot.version)

    async def instance(
        self, user_id: str, companion_id: str
    ) -> CompanionInstance | None:
        self._require_initialized()
        definition = self.definition(companion_id)
        snapshot = await self._database.get(
            StateAddress(_user_id(user_id), INSTANCE_STATE, definition.companion_id)
        )
        if snapshot is None:
            return None
        value = _state_mapping(snapshot.value, f"{INSTANCE_STATE}/{companion_id}")
        if set(value) != {"资质", "属性倍率"}:
            raise CompanionStateError("道侣轻实例字段不完整")
        multipliers_value = _state_mapping(value.get("属性倍率"), "道侣实例.属性倍率")
        if set(multipliers_value) != set(definition.fluctuating_attributes):
            raise CompanionStateError("道侣实例属性倍率与正式定义不一致")
        multipliers = {
            str(key): _state_positive_int(raw, f"道侣实例.属性倍率.{key}")
            for key, raw in multipliers_value.items()
        }
        return CompanionInstance(
            definition.companion_id,
            _state_positive_int(value.get("资质"), "道侣实例.资质"),
            MappingProxyType(multipliers),
            snapshot.version,
        )

    async def plan_gift(
        self,
        user_id: str,
        companion_id: str,
        *,
        item_id: str,
        grade_id: str,
        quantity: int,
        affection_gain: Decimal,
        occurred_at: str,
    ) -> CompanionGiftPlan:
        definition = self.definition(companion_id)
        normalized_item_id = str(item_id or "").strip()
        if normalized_item_id not in definition.favorite_item_ids:
            raise CompanionGiftError(f"{definition.name}并不喜欢这件物品")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise CompanionGiftError("赠礼数量必须是正整数")
        gain = _positive_affection(affection_gain, "赠礼好感")
        relation = await self.relation(user_id, definition.companion_id)
        after_affection = _quantize(relation.current_affection + gain)
        normalized_grade_id = str(grade_id or "").strip()
        if len(normalized_grade_id) != 2 or not normalized_grade_id.isdecimal():
            raise CompanionGiftError("赠礼品级编号无效")
        gift_key = f"{normalized_item_id}:{normalized_grade_id}"
        totals = dict(relation.gift_totals)
        totals[gift_key] = totals.get(gift_key, 0) + quantity
        first_full = (
            not relation.first_full_at
            and after_affection >= self.rules().full_reward_affection
        )
        first_full_at = occurred_at if first_full else relation.first_full_at
        after = CompanionRelation(
            definition.companion_id,
            after_affection,
            MappingProxyType(dict(sorted(totals.items()))),
            first_full_at,
            relation.first_invited_at,
            relation.version + 1,
        )
        return CompanionGiftPlan(
            relation,
            after,
            first_full,
            StateMutation(
                _user_id(user_id),
                RELATION_STATE,
                definition.companion_id,
                _relation_value(after),
                relation.version,
            ),
        )

    async def plan_invitation(
        self,
        user_id: str,
        companion_id: str,
        *,
        player_gender: str,
        occurred_at: str,
        random_source: random.Random | None = None,
    ) -> CompanionInvitationPlan:
        definition = self.definition(companion_id)
        relation = await self.relation(user_id, definition.companion_id)
        if relation.current_affection < self.rules().invitation_affection:
            raise CompanionInvitationError(
                f"当前好感为{_display_affection(relation.current_affection)}，"
                f"达到{_display_affection(self.rules().invitation_affection)}后才能邀约"
            )
        active = await self.active(user_id)
        instance = await self.instance(user_id, definition.companion_id)
        if active is not None:
            if active.companion_id == definition.companion_id:
                if instance is None:
                    raise CompanionStateError("同行道侣缺少轻实例")
                return CompanionInvitationPlan(relation, instance, False, True, ())
            active_name = self.definition(active.companion_id).name
            raise CompanionInvitationError(f"{active_name}正在与你同行，请先暂别")
        first_invitation = not relation.first_invited_at
        if (
            (first_invitation or self.rules().check_gender_again)
            and self.rules().first_invitation_gender_relation == "不同"
            and str(player_gender or "").strip() == definition.gender
        ):
            reason = "首次邀约" if first_invitation else "再次邀约"
            raise CompanionInvitationError(f"{reason}要求双方性别不同")
        if first_invitation:
            if instance is not None:
                raise CompanionStateError("未曾邀约的道侣已经存在轻实例")
            instance = self._new_instance(definition, random_source)
        elif instance is None:
            raise CompanionStateError("曾经邀约的道侣缺少轻实例")

        operations: list[StateMutation] = []
        if first_invitation:
            relation = CompanionRelation(
                relation.companion_id,
                relation.current_affection,
                relation.gift_totals,
                relation.first_full_at,
                occurred_at,
                relation.version + 1,
            )
            operations.append(
                StateMutation(
                    _user_id(user_id),
                    RELATION_STATE,
                    definition.companion_id,
                    _relation_value(relation),
                    relation.version - 1,
                )
            )
            operations.append(
                StateMutation(
                    _user_id(user_id),
                    INSTANCE_STATE,
                    definition.companion_id,
                    {
                        "资质": instance.qualification,
                        "属性倍率": dict(instance.attribute_multipliers),
                    },
                    0,
                )
            )
        operations.append(
            StateMutation(
                _user_id(user_id),
                ACTIVE_STATE,
                ACTIVE_KEY,
                {"道侣编号": definition.companion_id},
                0,
            )
        )
        return CompanionInvitationPlan(
            relation,
            instance,
            first_invitation,
            False,
            tuple(operations),
        )

    async def plan_farewell(
        self, user_id: str, companion_id: str
    ) -> CompanionFarewellPlan:
        definition = self.definition(companion_id)
        active = await self.active(user_id)
        if active is None:
            raise CompanionFarewellError("当前没有同行道侣")
        if active.companion_id != definition.companion_id:
            active_name = self.definition(active.companion_id).name
            raise CompanionFarewellError(f"当前与你同行的是{active_name}")
        return CompanionFarewellPlan(
            definition.companion_id,
            StateMutation(
                _user_id(user_id),
                ACTIVE_STATE,
                ACTIVE_KEY,
                None,
                active.version,
            ),
        )

    def _new_instance(
        self,
        definition: CompanionDefinition,
        random_source: random.Random | None,
    ) -> CompanionInstance:
        source = random_source or random.SystemRandom()
        qualification = source.randint(*definition.qualification_range)
        multipliers = {
            attribute: source.randint(*definition.attribute_multiplier_range)
            for attribute in definition.fluctuating_attributes
        }
        return CompanionInstance(
            definition.companion_id,
            qualification,
            MappingProxyType(multipliers),
            1,
        )

    def _load_rules(self) -> CompanionRules:
        value = _mapping(
            self._data.dataset("角色规则").get("道侣"),
            "规则/角色/主体/道侣.json",
        )
        invitation = _mapping(value.get("邀约"), "道侣.邀约")
        reward = _mapping(value.get("圆满回礼"), "道侣.圆满回礼")
        return CompanionRules(
            _positive_affection(value.get("赠礼每件好感"), "道侣.赠礼每件好感"),
            _positive_int(value.get("同行上限"), "道侣.同行上限"),
            _positive_affection(invitation.get("好感要求"), "道侣.邀约.好感要求"),
            _text(
                invitation.get("首次邀约性别关系"),
                "道侣.邀约.首次邀约性别关系",
            ),
            _bool(
                invitation.get("再次邀约检查性别"),
                "道侣.邀约.再次邀约检查性别",
            ),
            _positive_affection(reward.get("触发好感"), "道侣.圆满回礼.触发好感"),
            _positive_int(
                reward.get("每名道侣终身次数"),
                "道侣.圆满回礼.每名道侣终身次数",
            ),
        )

    def _realms(self) -> tuple[tuple[str, str, int, int], ...]:
        return tuple(
            (
                realm_id,
                _text(value.get("名称"), f"境界 {realm_id}.名称"),
                _positive_int(value.get("等级下限"), f"境界 {realm_id}.等级下限"),
                _positive_int(value.get("等级上限"), f"境界 {realm_id}.等级上限"),
            )
            for realm_id, value in self._data.entities("境界").items()
        )

    def _definition(
        self,
        companion_id: str,
        value: Mapping[str, object],
        realms: tuple[tuple[str, str, int, int], ...],
        grade_ids: frozenset[str],
    ) -> CompanionDefinition:
        record = self._data.entity_record("道侣", companion_id)
        location_name = _text(record.directory_owner, f"道侣 {companion_id}.归属地点")
        level = _positive_int(value.get("等级"), f"道侣 {companion_id}.等级")
        matches = tuple(
            (realm_id, realm_name)
            for realm_id, realm_name, minimum, maximum in realms
            if minimum <= level <= maximum
        )
        if len(matches) != 1:
            raise JsonDataError(f"道侣 {companion_id} 的等级无法唯一归属境界")
        identity = _mapping(value.get("身份"), f"道侣 {companion_id}.身份")
        join = _mapping(value.get("结交"), f"道侣 {companion_id}.结交")
        favorite_pools = tuple(
            _text(raw, f"道侣 {companion_id}.结交.灵植池")
            for raw in _sequence(join.get("灵植池"), "道侣.结交.灵植池")
        )
        favorite_items = frozenset(self._data.pool_members(favorite_pools, "物品"))
        if not favorite_items:
            raise JsonDataError(f"道侣 {companion_id} 的喜爱灵植池为空")
        for item_id in favorite_items:
            if self._data.entity_record("物品", item_id).number_category != "灵植":
                raise JsonDataError(f"道侣 {companion_id} 的喜爱池包含非灵植 {item_id}")
        reward_value = _mapping(join.get("圆满回礼"), "道侣.结交.圆满回礼")
        reward = CompanionReward(
            _text(reward_value.get("编号"), "圆满回礼.编号"),
            _text(reward_value.get("品级"), "圆满回礼.品级"),
            _positive_int(reward_value.get("数量"), "圆满回礼.数量"),
        )
        self._data.entity("物品", reward.item_id)
        if reward.grade_id not in grade_ids:
            raise JsonDataError(f"道侣 {companion_id} 使用未知回礼品级")
        fluctuation = _mapping(value.get("实力波动"), "道侣.实力波动")
        qualification = _integer_range(value.get("资质范围"), "道侣.资质范围")
        multiplier_range = _integer_range(fluctuation.get("倍率"), "道侣.实力波动.倍率")
        realm_id, realm_name = matches[0]
        return CompanionDefinition(
            companion_id,
            _text(value.get("名称"), f"道侣 {companion_id}.名称"),
            _text(value.get("性别"), f"道侣 {companion_id}.性别"),
            _text(identity.get("称号"), f"道侣 {companion_id}.身份.称号"),
            _text(identity.get("立场"), f"道侣 {companion_id}.身份.立场"),
            _text(identity.get("性格方向"), f"道侣 {companion_id}.身份.性格方向"),
            _text(value.get("说明"), f"道侣 {companion_id}.说明"),
            location_name,
            realm_id,
            realm_name,
            level,
            _bool(identity.get("可交互"), f"道侣 {companion_id}.身份.可交互"),
            favorite_pools,
            favorite_items,
            reward,
            CompanionDialogue(
                _text_sequence(identity.get("话语"), "道侣.身份.话语"),
                _text(join.get("喜好话语"), "道侣.结交.喜好话语"),
                _text_sequence(join.get("收礼话语"), "道侣.结交.收礼话语"),
                _text_sequence(join.get("婉拒话语"), "道侣.结交.婉拒话语"),
                _text(join.get("圆满话语"), "道侣.结交.圆满话语"),
                _text(join.get("邀约话语"), "道侣.结交.邀约话语"),
                _text(join.get("暂别话语"), "道侣.结交.暂别话语"),
            ),
            qualification,
            _text_sequence(fluctuation.get("属性"), "道侣.实力波动.属性"),
            multiplier_range,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("道侣核心微服务尚未初始化")


def _relation_value(relation: CompanionRelation) -> dict[str, object]:
    value: dict[str, object] = {
        "当前好感": _affection_json(relation.current_affection),
        "赠礼累计": dict(relation.gift_totals),
    }
    if relation.first_full_at:
        value["首次圆满时间"] = relation.first_full_at
    if relation.first_invited_at:
        value["首次邀约时间"] = relation.first_invited_at
    return value


def _affection_json(value: Decimal) -> int | float:
    normalized = _quantize(value)
    return (
        int(normalized) if normalized == normalized.to_integral() else float(normalized)
    )


def _display_affection(value: Decimal) -> str:
    return f"{_quantize(value):.1f}"


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_AFFECTION_QUANTUM, rounding=ROUND_HALF_UP)


def _positive_affection(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise JsonDataError(f"{label}必须是十进制数") from exc
    if not result.is_finite() or result <= 0:
        raise JsonDataError(f"{label}必须大于0")
    return _quantize(result)


def _state_affection(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CompanionStateError(f"{label}必须是十进制数") from exc
    if not result.is_finite() or result < 0:
        raise CompanionStateError(f"{label}不能小于0")
    return _quantize(result)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _state_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CompanionStateError(f"{label}必须是对象")
    return value


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是数组")
    result = tuple(value)
    if not result:
        raise JsonDataError(f"{label}不能为空")
    return result


def _text_sequence(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(raw, f"{label}[]") for raw in _sequence(value, label))


def _integer_range(value: object, label: str) -> tuple[int, int]:
    values = _sequence(value, label)
    if len(values) != 2:
        raise JsonDataError(f"{label}必须包含下限和上限")
    minimum = _positive_int(values[0], f"{label}.下限")
    maximum = _positive_int(values[1], f"{label}.上限")
    if minimum > maximum:
        raise JsonDataError(f"{label}下限不能大于上限")
    return minimum, maximum


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JsonDataError(f"{label}必须是非空字符串")
    return value.strip()


def _state_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CompanionStateError(f"{label}不能为空")
    return text


def _optional_text(value: object) -> str:
    return str(value or "").strip()


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _state_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CompanionStateError(f"{label}必须是正整数")
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise JsonDataError(f"{label}必须是布尔值")
    return value


def _normalize(value: object) -> str:
    return "".join(str(value or "").split()).casefold()


def _user_id(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("user_id不能为空")
    return normalized


__all__ = [
    "ACTIVE_KEY",
    "ACTIVE_STATE",
    "INSTANCE_STATE",
    "RELATION_STATE",
    "CompanionService",
]
