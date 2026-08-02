"""战斗核心公共微服务。"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from game.core.data import JsonDataService, materialize

from .catalog import BattleReportCatalog
from .contracts import (
    BUILD_SECTIONS,
    CombatantSpec,
    CombatRequest,
    CombatResult,
    CombatStatus,
)
from .engine import BattleEngine
from .foundation import load_battle_foundation
from .models import RuntimeCombatantSnapshot
from .presentation import build_battle_report_presentation
from .report import RuntimeBattleReportParticipant, build_battle_report


class CombatService:
    """消费 JSON 数据微服务，统一提供战斗执行与战报生成。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._engine: BattleEngine | None = None
        self._report_catalog: BattleReportCatalog | None = None

    def initialize(self) -> CombatStatus:
        if self._engine is not None:
            raise RuntimeError("战斗核心已经初始化")
        foundation = load_battle_foundation(self._data)
        report_dataset = materialize(self._data.dataset("战斗展示"))
        report_catalog = BattleReportCatalog.from_mapping(
            report_dataset["战报"]
        )
        self._engine = BattleEngine(foundation)
        self._report_catalog = report_catalog
        return self.status()

    def status(self) -> CombatStatus:
        engine = self._engine
        if engine is None:
            return CombatStatus(False, 0, 0, 0)
        return CombatStatus(
            initialized=True,
            mechanism_count=len(engine.catalog.mechanisms),
            ability_count=len(engine.catalog.abilities),
            event_count=len(engine.catalog.events),
        )

    async def execute(self, request: CombatRequest) -> CombatResult:
        """执行唯一的公共战斗请求，不阻塞异步消息驱动。"""

        return await asyncio.to_thread(self._execute_sync, request)

    def _execute_sync(self, request: CombatRequest) -> CombatResult:
        left = tuple(self._runtime_snapshot(value) for value in request.left_team)
        right = tuple(self._runtime_snapshot(value) for value in request.right_team)
        item_definitions = self._inventory_definitions((*request.left_team, *request.right_team))
        result = self._simulate_runtime_teams(
            left=left,
            right=right,
            item_definitions=item_definitions,
            seed=request.seed,
            action_limit=request.action_limit,
            share_left_inventory=request.share_left_inventory,
        )
        if request.report is None:
            return result
        return self._attach_report(result, request, (*left, *right))

    def _simulate_runtime_teams(
        self,
        *,
        left: tuple[RuntimeCombatantSnapshot, ...],
        right: tuple[RuntimeCombatantSnapshot, ...],
        item_definitions: dict[str, dict[str, Any]],
        seed: int,
        action_limit: int,
        share_left_inventory: bool = False,
    ) -> CombatResult:
        """供战斗服务自身测试和基准使用的内部同步入口。"""

        return self._require_engine().simulate_teams(
            left=left,
            right=right,
            item_definitions=item_definitions,
            seed=seed,
            action_limit=action_limit,
            share_left_inventory=share_left_inventory,
        )

    def _runtime_snapshot(self, value: CombatantSpec) -> RuntimeCombatantSnapshot:
        techniques = []
        for index, reference in enumerate(value.build):
            section = str(reference.section or "").strip()
            identity = str(reference.identity or "").strip()
            if section not in BUILD_SECTIONS:
                raise ValueError(f"战斗构筑不支持实体类别：{section or '<空>'}")
            definition = materialize(self._data.entity(section, identity))
            definition["实例"] = reference.instance_id or f"{value.id}:{section}:{index}"
            definition["出生序号"] = int(reference.born_order)
            definition["威力倍率"] = float(reference.power_multiplier)
            techniques.append(definition)
        battle_pills, pill_statuses = self._battle_pill_statuses(value)
        return RuntimeCombatantSnapshot(
            id=value.id,
            name=value.name,
            attributes=copy.deepcopy(dict(value.attributes)),
            level=value.level,
            kind=value.kind,
            weapon_attack=value.weapon_attack,
            techniques=tuple(techniques),
            health=value.health,
            spirit=value.spirit,
            shield=value.shield,
            statuses=tuple((*copy.deepcopy(value.statuses), *pill_statuses)),
            cooldowns=copy.deepcopy(dict(value.cooldowns)),
            inventory=copy.deepcopy(dict(value.inventory)),
            auto_medicine=value.auto_medicine,
            medicine_threshold=value.medicine_threshold,
            skill_cursor=value.skill_cursor,
            owner_id=value.owner_id,
            controller_id=value.controller_id,
            form=value.form,
            forms=copy.deepcopy(dict(value.forms)),
            tags=tuple(value.tags),
            tactic=tuple(copy.deepcopy(value.tactic)),
            battle_profile=copy.deepcopy(dict(value.battle_profile)),
            battle_pills=battle_pills,
        )

    def _battle_pill_statuses(
        self,
        combatant: CombatantSpec,
    ) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
        identities = tuple(str(value).strip() for value in combatant.battle_pills)
        if any(not value for value in identities):
            raise ValueError("战丹编号不能为空")
        if not identities:
            return (), ()

        alchemy_rules = materialize(self._data.dataset("炼药规则"))
        battle_pill_rules = dict(alchemy_rules["丹则"]["战丹"])
        repeat_rule = str(battle_pill_rules["同丹重复"])
        if repeat_rule not in {"允许", "禁止"}:
            raise ValueError(f"未知战丹重复规则：{repeat_rule}")
        if repeat_rule == "禁止" and len(identities) != len(set(identities)):
            raise ValueError("同一名参战者不能重复寄存同一枚战丹")
        strength_rules = {
            int(rule["强度"]): dict(rule)
            for rule in alchemy_rules["战丹"]["强度规则"]
        }
        slot_limit = int(battle_pill_rules["丹位上限"])
        used_slots = 0
        statuses: list[dict[str, Any]] = []
        for identity in identities:
            item = materialize(self._data.entity("物品", identity))
            effect = dict(item.get("使用效果") or {})
            if effect.get("类型") != "寄存战丹":
                raise ValueError(f"{identity}不是战丹")
            slots = int(item.get("丹位", 0))
            strength = int(item.get("强度", 0))
            strength_rule = strength_rules.get(strength)
            if strength_rule is None or slots < 1:
                raise ValueError(f"{identity}缺少有效的强度或丹位")
            expected_slots = int(strength_rule["丹位"])
            if slots != expected_slots:
                raise ValueError(
                    f"战丹{identity}强度{strength}应占用{expected_slots}个丹位"
                )
            used_slots += slots

            status = copy.deepcopy(dict(effect.get("战前状态") or {}))
            if status.get("持续单位") != "整场战斗":
                raise ValueError(f"{identity}的战前状态必须持续整场战斗")
            mechanism_ids = tuple(str(value) for value in effect.get("战斗机制") or ())
            listeners = list(copy.deepcopy(status.get("监听") or ()))
            for mechanism_id in mechanism_ids:
                mechanism = materialize(self._data.entity("机制", mechanism_id))
                node = copy.deepcopy(dict(mechanism["节点"]))
                if node.get("能力") != "监听事件":
                    raise ValueError(
                        f"战丹{identity}只能装配监听型战斗机制：{mechanism_id}"
                    )
                listeners.append(node)
            status["监听"] = listeners
            status["来源"] = combatant.id
            status["来源名称"] = str(item.get("名称") or identity)
            record = copy.deepcopy(dict(status.get("记录") or {}))
            record.update(
                {
                    "战丹编号": identity,
                    "战斗机制": list(mechanism_ids),
                    "强度": strength,
                    "丹位": slots,
                }
            )
            status["记录"] = record
            statuses.append(status)

        if used_slots > slot_limit:
            raise ValueError(f"寄存战丹占用{used_slots}个丹位，超过上限{slot_limit}")
        return identities, tuple(statuses)

    def _inventory_definitions(
        self,
        combatants: Sequence[CombatantSpec],
    ) -> dict[str, dict[str, Any]]:
        identities = {
            str(identity)
            for combatant in combatants
            for identity, quantity in combatant.inventory.items()
            if int(quantity) > 0
        }
        return {
            identity: materialize(self._data.entity("物品", identity))
            for identity in sorted(identities)
        }

    def _attach_report(
        self,
        result: CombatResult,
        request: CombatRequest,
        runtime_snapshots: tuple[RuntimeCombatantSnapshot, ...],
    ) -> CombatResult:
        report_spec = request.report
        if report_spec is None:
            return result
        metadata = {value.id: value for value in report_spec.participants}
        if len(metadata) != len(report_spec.participants):
            raise ValueError("战报补充信息的参战者 ID 不能重复")
        requested = (*request.left_team, *request.right_team)
        requested_by_id = {value.id: value for value in requested}
        unknown = set(metadata) - set(requested_by_id)
        if unknown:
            raise ValueError("战报补充信息引用未知参战者：" + "、".join(sorted(unknown)))
        runtime_by_id = {value.id: value for value in runtime_snapshots}
        participants = []
        for value in (*result.left_results, *result.right_results):
            original = requested_by_id.get(value.id)
            runtime = runtime_by_id.get(value.id)
            display = metadata.get(value.id)
            attributes = dict(value.attributes)
            participants.append(
                RuntimeBattleReportParticipant(
                    id=value.id,
                    name=value.name,
                    title=(display.title if display and display.title else value.kind),
                    attributes=attributes,
                    initial_health=(
                        value.health
                        if original is None
                        else float(
                            original.health
                            if original.health is not None
                            else attributes.get("血气上限", value.health)
                        )
                    ),
                    final_health=value.health,
                    initial_spirit=(
                        value.spirit
                        if original is None
                        else float(
                            original.spirit
                            if original.spirit is not None
                            else attributes.get("精神上限", value.spirit)
                        )
                    ),
                    final_spirit=value.spirit,
                    initial_shield=original.shield if original is not None else value.shield,
                    final_shield=value.shield,
                    initial_statuses=original.statuses if original is not None else (),
                    statuses=value.statuses,
                    techniques=runtime.techniques if runtime is not None else (),
                    moves=display.moves if display else (),
                    mechanisms=display.mechanisms if display else (),
                    ability_definitions=self._require_engine().catalog.abilities,
                    color=display.color if display else "",
                    extra=display.extra if display else {},
                    level=value.level,
                    kind=value.kind,
                )
            )
        report = build_battle_report(
            result,
            participants,
            catalog=self._require_report_catalog(),
            seed=request.seed,
            generated_at=report_spec.generated_at,
            scene=report_spec.scene,
        )
        presentation = (
            build_battle_report_presentation(
                report,
                self._require_report_catalog(),
            )
            if report_spec.include_presentation
            else None
        )
        return replace(result, report=report, presentation=presentation)

    def _require_engine(self) -> BattleEngine:
        if self._engine is None:
            raise RuntimeError("战斗核心尚未初始化")
        return self._engine

    def _require_report_catalog(self) -> BattleReportCatalog:
        if self._report_catalog is None:
            raise RuntimeError("战斗核心尚未初始化")
        return self._report_catalog


__all__ = ["CombatService"]
