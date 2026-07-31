"""战斗核心公共微服务。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from game.core.data import JsonDataService

from .catalog import BattleReportCatalog
from .engine import BattleEngine
from .foundation import load_battle_foundation
from .models import BattleOutcome, CombatantSnapshot
from .presentation import build_battle_report_presentation
from .report import BattleReportParticipant, build_battle_report


@dataclass(frozen=True)
class CombatStatus:
    initialized: bool
    mechanism_count: int
    ability_count: int
    event_count: int


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
        report_catalog = BattleReportCatalog.from_mapping(
            self._data.read("展示/战报.json")
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

    def simulate(
        self,
        *,
        left: CombatantSnapshot,
        right: CombatantSnapshot,
        item_definitions: dict[str, dict[str, Any]],
        seed: int,
        action_limit: int,
    ) -> BattleOutcome:
        return self._require_engine().simulate(
            left=left,
            right=right,
            item_definitions=item_definitions,
            seed=seed,
            action_limit=action_limit,
        )

    def simulate_teams(
        self,
        *,
        left: tuple[CombatantSnapshot, ...],
        right: tuple[CombatantSnapshot, ...],
        item_definitions: dict[str, dict[str, Any]],
        seed: int,
        action_limit: int,
        share_left_inventory: bool = False,
    ) -> BattleOutcome:
        return self._require_engine().simulate_teams(
            left=left,
            right=right,
            item_definitions=item_definitions,
            seed=seed,
            action_limit=action_limit,
            share_left_inventory=share_left_inventory,
        )

    def build_report(
        self,
        outcome: BattleOutcome,
        participants: Sequence[BattleReportParticipant],
        *,
        seed: int | None = None,
        generated_at: str | None = None,
        scene: str = "青岚山演武台",
    ) -> dict[str, Any]:
        return build_battle_report(
            outcome,
            participants,
            catalog=self._require_report_catalog(),
            seed=seed,
            generated_at=generated_at,
            scene=scene,
        )

    def build_presentation(
        self,
        report: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return build_battle_report_presentation(
            report,
            self._require_report_catalog(),
        )

    def _require_engine(self) -> BattleEngine:
        if self._engine is None:
            raise RuntimeError("战斗核心尚未初始化")
        return self._engine

    def _require_report_catalog(self) -> BattleReportCatalog:
        if self._report_catalog is None:
            raise RuntimeError("战斗核心尚未初始化")
        return self._report_catalog


__all__ = ["CombatService", "CombatStatus"]
