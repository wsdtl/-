"""战丹必须由稳定物品编号装配，并由战斗核心执行其监听机制。"""

from __future__ import annotations

from pathlib import Path

import pytest

from game.core.alchemy import AlchemyError, AlchemyService
from game.core.combat import CombatantSpec, CombatRequest, CombatService
from game.core.data import JsonDataService
from game.core.item import ItemService


def test_battle_pill_is_resolved_into_runtime_listeners() -> None:
    combat, alchemy = _services()

    snapshot = combat._runtime_snapshot(
        _combatant(
            "left",
            prepared_statuses=alchemy.prepare_battle_pills(
                ("100087",), source_id="left"
            ).statuses,
        )
    )

    assert len(snapshot.statuses) == 1
    status = snapshot.statuses[0]
    assert len(status["监听"]) == 2
    assert status["记录"] == {
        "战丹编号": "100087",
        "战斗机制": ["600030", "600031"],
        "强度": 3,
        "丹位": 2,
    }


def test_fatal_guard_battle_pill_prevents_first_death() -> None:
    combat, alchemy = _services()
    request = CombatRequest(
        left_team=(
            _combatant(
                "left",
                health=20,
                speed=1,
                prepared_statuses=alchemy.prepare_battle_pills(
                    ("100039",), source_id="left"
                ).statuses,
            ),
        ),
        right_team=(_combatant("right", attack=500, speed=200),),
        seed=7,
        action_limit=1,
    )

    result = combat._execute_sync(request)

    assert result.left.health > 0
    assert any(event.mechanism == "600023" for event in result.events)


def test_battle_pill_rejects_duplicate_identity() -> None:
    _, alchemy = _services()

    with pytest.raises(AlchemyError, match="不能重复寄存"):
        alchemy.prepare_battle_pills(("100019", "100019"), source_id="left")


def test_battle_pill_rejects_slot_overflow() -> None:
    _, alchemy = _services()

    with pytest.raises(AlchemyError, match="超过上限 3"):
        alchemy.prepare_battle_pills(("100018", "100027"), source_id="left")


def test_battle_pill_rejects_non_battle_medicine() -> None:
    _, alchemy = _services()

    with pytest.raises(AlchemyError, match="物品不是战丹：100001"):
        alchemy.prepare_battle_pills(("100001",), source_id="left")


def _services() -> tuple[CombatService, AlchemyService]:
    data = JsonDataService(Path(__file__).resolve().parents[1] / "data")
    data.initialize()
    combat = CombatService(data)
    combat.initialize()
    items = ItemService(data)
    items.initialize()
    alchemy = AlchemyService(data, items)
    alchemy.initialize()
    return combat, alchemy


def _combatant(
    identity: str,
    *,
    attack: float = 20,
    speed: float = 100,
    health: float | None = None,
    prepared_statuses=(),
) -> CombatantSpec:
    return CombatantSpec(
        id=identity,
        name=identity,
        attributes={
            "血气上限": 100,
            "精神上限": 20,
            "攻击": attack,
            "防御": 0,
            "速度": speed,
            "命中率": 100,
        },
        health=health,
        prepared_statuses=prepared_statuses,
    )
