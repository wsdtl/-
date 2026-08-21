"""宗门战核心：战书、阵容锁定、多人战斗和灵石结算。"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from uuid import uuid4

from game.core.character import CharacterService
from game.core.combat import CombatRequest, CombatService
from game.core.companion import CompanionService
from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    SharedEntityMutation,
    TransactionCommand,
)
from game.core.location import LocationService
from game.core.player_state import PlayerStateService, StateTransitionCommand
from game.core.sect import SectService
from game.core.sect_assets import SectAssetService

from .contracts import SectWarError, SectWarStatus, SectWarView

ENTITY_TYPE = "宗门战"
STATE_TYPE = "sect_war"
MAIN_KEY = "main"

class SectWarService:
    state_types = frozenset({STATE_TYPE})

    def __init__(self, data: JsonDataService, database: DatabaseService,
                 sect: SectService, sect_assets: SectAssetService,
                 location: LocationService, character: CharacterService,
                 companion: CompanionService, player_state: PlayerStateService,
                 combat: CombatService) -> None:
        self._data, self._db, self._sect, self._assets = data, database, sect, sect_assets
        self._location, self._character, self._companion = location, character, companion
        self._state, self._combat = player_state, combat
        self._initialized = False
        self._seconds = self._maximum = self._actions = 0
        self._challenge_seconds = 0
        self._behavior = ""
        self._win_ratio = Decimal(0)
        self._draw_ratio = Decimal(0)

    def initialize(self) -> SectWarStatus:
        if self._initialized:
            raise RuntimeError("宗门战核心已经初始化")
        rule = _mapping(self._data.dataset("宗门规则").get("宗门战"), "宗门战.json")
        battle = _mapping(rule.get("战斗"), "宗门战.战斗")
        participants = _mapping(rule.get("参战"), "宗门战.参战")
        wager = _mapping(rule.get("押注"), "宗门战.押注")
        challenge = _mapping(rule.get("约战"), "宗门战.约战")
        self._challenge_seconds = _positive(
            challenge.get("有效秒数"), "宗门战.约战.有效秒数"
        )
        self._seconds = _positive(battle.get("结算秒数"), "宗门战.战斗.结算秒数")
        self._actions = _positive(battle.get("战斗行动上限"), "宗门战.战斗.战斗行动上限")
        self._maximum = _positive(participants.get("玩家上限"), "宗门战.参战.玩家上限")
        self._win_ratio = _ratio(wager.get("胜方比例"), "宗门战.押注.胜方比例")
        self._draw_ratio = _ratio(wager.get("平局返还比例"), "宗门战.押注.平局返还比例")
        self._behavior = _text(_mapping(rule.get("状态"), "宗门战.状态").get("行为"), "宗门战.状态.行为")
        if self._state.state_type(self._behavior) != "行为":
            raise JsonDataError("宗门战状态必须引用行为状态")
        self._initialized = True
        return self.status()

    def status(self) -> SectWarStatus:
        return SectWarStatus(self._initialized, self._seconds, self._maximum)

    async def challenge(self, user_id: str, target_name: str, wager: int, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id)
        if wager < 1: raise SectWarError("押注必须为正整数")
        target = await self._db.get_shared_entity_by_name("宗门", target_name.strip())
        if target is None or target.entity_id == member.sect_id: raise SectWarError("目标宗门不存在")
        location = await self._location.current(user_id)
        if location.space_type != "地表": raise SectWarError("宗门战必须在地表发起")
        if await self._active(member.sect_id) or await self._active(target.entity_id): raise SectWarError("已有未结束的宗门战")
        war_id = uuid4().hex[:20]
        value = {"宗门战编号": war_id, "状态": "待应战", "甲方": member.sect_id, "乙方": target.entity_id,
                 "坐标": list(location.xy), "押注": wager, "甲方锁定": False, "乙方锁定": False,
                 "创建时间": _now().isoformat(), "结束时间": "", "胜方": ""}
        stone_operation = await self._assets.plan_spirit_stone_change(
            member.sect_id, -wager
        )
        await self._commit(
            user_id,
            request_id,
            "发起宗门战",
            (stone_operation, SharedEntityMutation(ENTITY_TYPE, war_id, value, 0)),
            value,
        )
        return await self._view(value)

    async def accept(self, user_id: str, war_id: str, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id)
        record = await self._record(war_id)
        value = dict(record.value)
        if value.get("状态") != "待应战" or value.get("乙方") != member.sect_id:
            raise SectWarError("战书无效")
        if _now() >= _time(value.get("创建时间")) + timedelta(seconds=self._challenge_seconds):
            raise SectWarError("战书已经过期")
        value["状态"] = "备战"
        wager = int(value.get("押注") or 0)
        value["乙方押注"] = wager
        stone_operation = await self._assets.plan_spirit_stone_change(
            member.sect_id, -wager
        )
        await self._commit(
            user_id,
            request_id,
            "接受宗门战",
            (stone_operation, SharedEntityMutation(ENTITY_TYPE, war_id, value, record.version)),
            value,
        )
        return await self._view(value)

    async def lock(self, user_id: str, war_id: str, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id); record = await self._record(war_id); value = dict(record.value)
        side = "甲方" if value.get("甲方") == member.sect_id else "乙方" if value.get("乙方") == member.sect_id else ""
        if not side or value.get("状态") != "备战": raise SectWarError("当前不能锁定宗门战")
        if value.get(f"{side}锁定"):
            raise SectWarError("本方已经锁定宗门战")
        follow = await self._sect.follow(member.sect_id)
        if follow is None or follow.leader_user_id != (await self._sect.sect(member.sect_id)).leader_user_id: raise SectWarError("请先召集宗门同行")
        if len(follow.member_user_ids) > self._maximum: raise SectWarError("参战人数超过上限")
        locations = [await self._location.current(uid) for uid in follow.member_user_ids]
        xy = tuple(value.get("坐标", ()))
        if any(loc.space_type != "地表" or loc.xy != xy for loc in locations): raise SectWarError("双方必须在约定的地表坐标")
        value[f"{side}锁定"] = True; value[f"{side}成员"] = list(follow.member_user_ids)
        if value.get("甲方锁定") and value.get("乙方锁定"):
            value["状态"] = "已锁定"
        state_plans = tuple(
            await self._state.plan_transition(
                StateTransitionCommand(
                    participant,
                    request_id,
                    "行为",
                    self._behavior,
                    {"宗门战编号": war_id, "宗门编号": member.sect_id},
                )
            )
            for participant in follow.member_user_ids
        )
        await self._commit(
            user_id,
            request_id,
            "锁定宗门战",
            (SharedEntityMutation(ENTITY_TYPE, war_id, value, record.version),)
            + tuple(plan.mutation for plan in state_plans),
            value,
        )
        return await self._view(value)

    async def start(self, user_id: str, war_id: str, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id); record = await self._record(war_id); value = dict(record.value)
        if value.get("状态") != "已锁定": raise SectWarError("双方尚未锁定阵容")
        if member.sect_id not in (value.get("甲方"), value.get("乙方")): raise SectWarError("无权限")
        left = await self._combatants(tuple(value["甲方成员"])); right = await self._combatants(tuple(value["乙方成员"]))
        result = await self._combat.execute(CombatRequest(tuple(left), tuple(right), _seed(war_id), self._actions))
        now = _now(); value.update({"状态": "战斗中", "开始时间": now.isoformat(), "结束时间": (now + timedelta(seconds=self._seconds)).isoformat(),
                                    "胜方": result.winner_side or "平局", "甲方存活": sum(x.alive for x in result.left_results), "乙方存活": sum(x.alive for x in result.right_results)})
        value["战果"] = {
            item.id: {"用户编号": item.owner_id, "道侣": item.id.startswith("companion:"),
                      "血气": item.health, "精神": item.spirit}
            for item in (*result.left_results, *result.right_results)
        }
        await self._commit(user_id, request_id, "开始宗门战", (SharedEntityMutation(ENTITY_TYPE, war_id, value, record.version),), value)
        return await self._view(value)

    async def view(self, war_id: str) -> SectWarView: return await self._view((await self._record(war_id)).value)

    async def settle(self, user_id: str, war_id: str, request_id: str) -> SectWarView:
        await self._member_officer(user_id); record = await self._record(war_id); value = dict(record.value)
        if value.get("状态") != "战斗中": return await self._view(value)
        if _now() < _time(value.get("结束时间")): raise SectWarError("宗门战尚未结束")
        result_rows = _mapping(value.get("战果"), "宗门战.战果")
        operations = []
        for raw in result_rows.values():
            item = _mapping(raw, "宗门战.战果[]")
            owner = _text(item.get("用户编号"), "战果.用户编号")
            if bool(item.get("道侣")):
                plan = await self._companion.plan_battle_settlement(
                    owner,
                    health=float(item.get("血气") or 0),
                    spirit=float(item.get("精神") or 0),
                )
                operations.append(plan.operation)
            else:
                plan = await self._character.plan_battle_settlement(
                    owner,
                    health=float(item.get("血气") or 0),
                    spirit=float(item.get("精神") or 0),
                )
                operations.extend(plan.operations)
        winner = str(value.get("胜方") or "平局")
        total = int(value.get("押注") or 0) * 2
        if winner == "left":
            operations.append(await self._assets.plan_spirit_stone_change(value["甲方"], _payout(total, self._win_ratio)))
        elif winner == "right":
            operations.append(await self._assets.plan_spirit_stone_change(value["乙方"], _payout(total, self._win_ratio)))
        else:
            refund = _payout(int(value.get("押注") or 0), self._draw_ratio)
            operations.extend((await self._assets.plan_spirit_stone_change(value["甲方"], refund), await self._assets.plan_spirit_stone_change(value["乙方"], refund)))
        value["状态"] = "已结算"
        operations.insert(0, SharedEntityMutation(ENTITY_TYPE, war_id, value, record.version))
        for participant in tuple(value.get("甲方成员", ())) + tuple(value.get("乙方成员", ())):
            snapshot = await self._state.current(participant)
            if snapshot is not None and snapshot.states["行为"].state_id == self._behavior:
                plan = await self._state.plan_finish_behavior(participant, expected_version=snapshot.version)
                operations.append(plan.mutation)
        await self._commit(user_id, request_id, "结算宗门战", tuple(operations), value)
        return await self._view(value)

    async def _combatants(self, ids: tuple[str, ...]):
        result = []
        for uid in ids:
            result.append(await self._character.combatant(uid))
            companion = await self._companion.combatant(uid)
            if companion is not None: result.append(companion)
        return result

    async def _member_officer(self, user_id: str):
        member = await self._sect.membership(user_id)
        if member is None or not self._sect.is_officer(member.role): raise SectWarError("只有宗主或长老可以操作")
        return member
    async def _record(self, war_id: str):
        record = await self._db.get_shared_entity(ENTITY_TYPE, war_id)
        if record is None: raise SectWarError("没有找到这份战书")
        return record
    async def _active(self, sect_id: str) -> bool:
        now = _now()
        for record in await self._db.list_shared_entities(ENTITY_TYPE):
            value = record.value
            if sect_id not in (value.get("甲方"), value.get("乙方")):
                continue
            status = value.get("状态")
            if status in {"已结算", "已拒绝", "已过期"}:
                continue
            if (
                status == "待应战"
                and value.get("创建时间")
                and now >= _time(value["创建时间"])
                + timedelta(seconds=self._challenge_seconds)
            ):
                continue
            return True
        return False
    async def _view(self, raw: Mapping[str, object]) -> SectWarView:
        a = await self._sect.sect(str(raw.get("甲方"))); b = await self._sect.sect(str(raw.get("乙方")))
        return SectWarView(str(raw.get("宗门战编号")), str(raw.get("甲方")), str(raw.get("乙方")), a.name if a else "", b.name if b else "", str(raw.get("状态")), int(raw.get("押注") or 0), len(raw.get("甲方成员", [])), len(raw.get("乙方成员", [])), _time(raw.get("结束时间")) if raw.get("结束时间") else None, str(raw.get("胜方") or ""))
    async def _commit(self, user_id, request_id, business, operations, payload):
        await self._db.commit(TransactionCommand(user_id, request_id, business, tuple(operations), payload))

def _mapping(value, label):
    if not isinstance(value, Mapping): raise JsonDataError(f"{label}必须是对象")
    return value
def _text(value, label):
    if not isinstance(value, str) or not value.strip(): raise JsonDataError(f"{label}必须是非空字符串")
    return value.strip()
def _positive(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1: raise JsonDataError(f"{label}必须是正整数")
    return value


def _ratio(value, label):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise JsonDataError(f"{label}必须是0至1之间的小数") from exc
    if result < 0 or result > 1:
        raise JsonDataError(f"{label}必须是0至1之间的小数")
    return result


def _payout(amount: int, ratio: Decimal) -> int:
    return int((Decimal(amount) * ratio).to_integral_value(rounding=ROUND_FLOOR))


def _now(): return datetime.now(timezone.utc)
def _time(value): return datetime.fromisoformat(str(value)).astimezone(timezone.utc)
def _seed(value): return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")

__all__ = ["ENTITY_TYPE", "STATE_TYPE", "SectWarService"]
