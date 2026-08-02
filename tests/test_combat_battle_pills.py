"""战丹必须由稳定物品编号装配，并由战斗核心执行其监听机制。"""

from __future__ import annotations

from pathlib import Path

import pytest

from game.core.combat import CombatantSpec, CombatRequest, CombatService
from game.core.data import JsonDataService


def test_battle_pill_is_resolved_into_runtime_listeners() -> None:
    combat = _combat()

    snapshot = combat._runtime_snapshot(
        _combatant("left", battle_pills=("100087",))
    )

    assert snapshot.battle_pills == ("100087",)
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
    combat = _combat()
    request = CombatRequest(
        left_team=(
            _combatant(
                "left",
                health=20,
                speed=1,
                battle_pills=("100039",),
            ),
        ),
        right_team=(
            _combatant("right", attack=500, speed=200),
        ),
        seed=7,
        action_limit=1,
    )

    result = combat._execute_sync(request)

    assert result.left.health > 0
    assert result.left.battle_pills == ("100039",)
    assert any(event.mechanism == "600023" for event in result.events)


def test_battle_pill_rejects_duplicate_identity() -> None:
    combat = _combat()

    with pytest.raises(ValueError, match="不能重复寄存"):
        combat._runtime_snapshot(
            _combatant("left", battle_pills=("100019", "100019"))
        )


def test_battle_pill_rejects_slot_overflow() -> None:
    combat = _combat()

    with pytest.raises(ValueError, match="超过上限3"):
        combat._runtime_snapshot(
            _combatant("left", battle_pills=("100018", "100027"))
        )


def test_battle_pill_rejects_non_battle_medicine() -> None:
    combat = _combat()

    with pytest.raises(ValueError, match="100001不是战丹"):
        combat._runtime_snapshot(_combatant("left", battle_pills=("100001",)))


def _combat() -> CombatService:
    data = JsonDataService(Path(__file__).resolve().parents[1] / "data")
    data.initialize()
    combat = CombatService(data)
    combat.initialize()
    return combat


def _combatant(
    identity: str,
    *,
    attack: float = 20,
    speed: float = 100,
    health: float | None = None,
    battle_pills: tuple[str, ...] = (),
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
        battle_pills=battle_pills,
    )
