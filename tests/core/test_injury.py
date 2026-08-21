from __future__ import annotations

import asyncio
from pathlib import Path

from game.core.combat import BattleEvent, CombatantResult, StatusResult
from game.core.data import JsonDataService
from game.core.database import DatabaseService, TransactionCommand
from game.core.injury import (
    PLAYER_KEY,
    InjuryEntry,
    InjuryService,
    InjurySource,
    InjuryState,
    companion_subject,
)


def _run(awaitable):
    return asyncio.run(awaitable)


def _service(tmp_path: Path) -> tuple[JsonDataService, DatabaseService, InjuryService]:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    injury = InjuryService(data, database)
    injury.initialize()
    return data, database, injury


def _result(
    *,
    health: float = 100,
    spirit: float = 100,
    statuses: tuple[StatusResult, ...] = (),
) -> CombatantResult:
    return CombatantResult(
        id="player:user-1",
        name="闻人照",
        attributes={"血气上限": 100, "精神上限": 100},
        level=1,
        combatant_type="修士",
        health=health,
        spirit=spirit,
        shield=0,
        statuses=statuses,
        cooldowns={},
        inventory={},
        consumed_items={},
        inventory_owner_id="user-1",
        skill_cursor=0,
        owner_id="user-1",
    )


def _status(
    name: str,
    source: str,
    *,
    modifiers: dict[str, float] | None = None,
    action_limits: tuple[str, ...] = (),
) -> StatusResult:
    return StatusResult(
        name=name,
        category="负面",
        remaining_turns=2,
        source=source,
        source_name=source,
        source_mechanism="",
        modifiers=modifiers or {},
        stacks=1,
        max_stacks=3,
        tags=(),
        duration_unit="状态承受者行动",
        action_limits=action_limits,
        effect_immunities=(),
        listeners=(),
        values={},
        expire_with_source=False,
    )


def test_every_realm_has_six_self_generated_injuries(tmp_path: Path) -> None:
    data, database, injury = _service(tmp_path)

    counts = {}
    external = 0
    for value in data.entities("伤势").values():
        if value["来源类别"] == "境界自生":
            counts[value["境界"]] = counts.get(value["境界"], 0) + 1
        else:
            external += 1

    assert set(counts) == set(data.entities("境界"))
    assert set(counts.values()) == {6}
    assert injury.status().self_generated_count == 120
    assert external == injury.status().external_count == 12
    database.close()


def test_evolution_filters_external_sources_and_limits_self_injuries(
    tmp_path: Path,
) -> None:
    _, database, injury = _service(tmp_path)
    state = InjuryState("user-1", PLAYER_KEY, (), 0)
    result = _result(
        health=0,
        spirit=0,
        statuses=(_status("裂创", "enemy:1"), _status("蚀脉", "ally:1")),
    )
    events = (
        BattleEvent(
            1,
            "受到致命伤害",
            "敌修",
            "闻人照",
            "",
            source_id="enemy:1",
            target_id=result.id,
        ),
    )

    evolved = injury.evolve(
        state,
        realm_id="510001",
        combatant_result=result,
        events=events,
        enemy_ids=("enemy:1",),
        battle_id="battle-1",
    )

    assert {entry.name for entry in evolved.state.entries} == {
        "裂创",
        "灵息浮游",
        "纳气失序",
    }
    assert "蚀脉" not in {entry.name for entry in evolved.state.entries}
    assert sum(change.category == "境界自生" for change in evolved.changes) == 2
    database.close()


def test_injury_stacks_cap_and_persists_without_new_trigger(tmp_path: Path) -> None:
    _, database, injury = _service(tmp_path)
    state = InjuryState("user-1", PLAYER_KEY, (), 0)
    for index in range(5):
        state = injury.evolve(
            state,
            realm_id="510001",
            combatant_result=_result(statuses=(_status("裂创", "enemy:1"),)),
            events=(),
            enemy_ids=("enemy:1",),
            battle_id=f"battle-{index}",
        ).state

    entry = next(value for value in state.entries if value.injury_id == "620001")
    assert entry.stacks == 3
    unchanged = injury.evolve(
        state,
        realm_id="510001",
        combatant_result=_result(),
        events=(),
        enemy_ids=("enemy:1",),
        battle_id="battle-final",
    ).state
    assert unchanged.entries == state.entries
    database.close()


def test_existing_named_debuff_is_classified_by_its_real_effect(tmp_path: Path) -> None:
    _, database, injury = _service(tmp_path)
    state = InjuryState("user-1", PLAYER_KEY, (), 0)

    evolved = injury.evolve(
        state,
        realm_id="510001",
        combatant_result=_result(
            statuses=(
                _status(
                    "万蛊蚀天",
                    "enemy:1",
                    modifiers={"攻击": -6, "防御": -6},
                ),
            )
        ),
        events=(),
        enemy_ids=("enemy:1",),
        battle_id="battle-1",
    )

    assert [(entry.injury_id, entry.name) for entry in evolved.state.entries] == [
        ("620006", "层裂")
    ]
    database.close()


def test_prepared_status_keeps_layers_and_action_limits(tmp_path: Path) -> None:
    _, database, injury = _service(tmp_path)
    state = InjuryState(
        "user-1",
        PLAYER_KEY,
        (
            InjuryEntry(
                "620003",
                "缄脉",
                "外来伤势",
                2,
                1,
                0,
                (InjurySource("battle-1", "外来伤势", "enemy:1", "敌修"),),
            ),
        ),
        0,
    )

    prepared = injury.prepared_statuses(state)[0]

    assert prepared.stacks == 2
    assert prepared.maximum_stacks == 3
    assert prepared.action_limits == ("技能",)
    assert prepared.metadata == (("伤势编号", "620003"),)
    database.close()


def test_retreat_treatment_uses_full_rounds_and_isolates_subjects(
    tmp_path: Path,
) -> None:
    _, database, injury = _service(tmp_path)
    player = InjuryState(
        "user-1",
        PLAYER_KEY,
        (
            InjuryEntry(
                "622001",
                "劫痕难消",
                "境界自生",
                1,
                1,
                0,
                (InjurySource("battle-1", "境界自生", "player:user-1", "闻人照"),),
            ),
        ),
        0,
    )
    companion_key = companion_subject("420001")
    companion = InjuryState(
        "user-1",
        companion_key,
        (
            InjuryEntry(
                "620001",
                "裂创",
                "外来伤势",
                1,
                1,
                0,
                (InjurySource("battle-1", "外来伤势", "enemy:1", "敌修"),),
            ),
        ),
        0,
    )
    _run(
        database.commit(
            TransactionCommand(
                "user-1",
                "seed-injuries",
                "测试伤势",
                (
                    injury.settlement_mutation(player),
                    injury.settlement_mutation(companion),
                ),
                {},
            )
        )
    )

    first = _run(injury.plan_treatment("user-1", PLAYER_KEY, 1))
    assert first.state.entries[0].treatment_progress == 1
    assert first.changes == ()
    _run(
        database.commit(
            TransactionCommand(
                "user-1",
                "first-treatment",
                "测试疗伤",
                (first.mutation,),
                {},
            )
        )
    )
    second = _run(injury.plan_treatment("user-1", PLAYER_KEY, 2))
    assert second.state.entries == ()
    assert len(second.changes) == 1

    companion_after = _run(injury.state("user-1", companion_key))
    assert companion_after.entries[0].name == "裂创"
    assert companion_after.entries[0].stacks == 1
    database.close()
