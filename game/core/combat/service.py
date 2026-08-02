"""战斗核心公共微服务。"""

from __future__ import annotations

import asyncio
import copy
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
    CombatStatusSpec,
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
        report_catalog = BattleReportCatalog.from_mapping(report_dataset["战报"])
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
        medicine_definitions = self._medicine_definitions(request)
        result = self._simulate_runtime_teams(
            left=left,
            right=right,
            medicine_definitions=medicine_definitions,
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
        medicine_definitions: dict[str, Any],
        seed: int,
        action_limit: int,
        share_left_inventory: bool = False,
    ) -> CombatResult:
        """供战斗服务自身测试和基准使用的内部同步入口。"""

        return self._require_engine().simulate_teams(
            left=left,
            right=right,
            medicine_definitions=medicine_definitions,
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
            definition["实例"] = (
                reference.instance_id or f"{value.id}:{section}:{index}"
            )
            definition["出生序号"] = int(reference.born_order)
            definition["威力倍率"] = float(reference.power_multiplier)
            techniques.append(definition)
        prepared_statuses = tuple(
            self._prepared_status(status) for status in value.prepared_statuses
        )
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
            statuses=(*copy.deepcopy(value.statuses), *prepared_statuses),
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
        )

    def _prepared_status(self, value: CombatStatusSpec) -> dict[str, Any]:
        listeners = []
        for mechanism_id in value.mechanism_ids:
            mechanism = materialize(self._data.entity("机制", mechanism_id))
            node = copy.deepcopy(dict(mechanism["节点"]))
            if node.get("能力") != "监听事件":
                raise ValueError(f"战前状态只能装配监听型战斗机制：{mechanism_id}")
            listeners.append(node)
        record = dict(value.metadata)
        if value.mechanism_ids:
            record["战斗机制"] = list(value.mechanism_ids)
        return {
            "名称": value.name,
            "类别": value.category,
            "剩余行动": value.remaining_actions,
            "持续单位": value.duration_unit,
            "属性": dict(value.modifiers),
            "标签": list(value.tags),
            "监听": listeners,
            "来源": value.source,
            "来源名称": value.source_name,
            "记录": record,
        }

    @staticmethod
    def _medicine_definitions(request: CombatRequest) -> dict[str, Any]:
        definitions = {value.identity: value for value in request.medicine_definitions}
        if len(definitions) != len(request.medicine_definitions):
            raise ValueError("恢复丹定义编号不能重复")
        inventory_ids = {
            str(identity)
            for combatant in (*request.left_team, *request.right_team)
            for identity, quantity in combatant.inventory.items()
            if int(quantity) > 0
        }
        unknown = set(definitions) - inventory_ids
        if unknown:
            raise ValueError(
                "恢复丹定义未被任何参战者携带：" + "、".join(sorted(unknown))
            )
        return definitions

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
            raise ValueError(
                "战报补充信息引用未知参战者：" + "、".join(sorted(unknown))
            )
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
                    initial_shield=original.shield
                    if original is not None
                    else value.shield,
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
