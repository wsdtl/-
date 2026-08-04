"""战场环境的位置来源、阶段计量与战斗执行回归测试。"""

from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from pathlib import Path

from game.core.battlefield import BattlefieldService
from game.core.combat import (
    CombatantSpec,
    CombatReportSpec,
    CombatRequest,
    CombatService,
)
from game.core.data import JsonDataService
from game.core.world import WorldService


def test_surface_field_accepts_location_name_and_exact_xy() -> None:
    _, world, battlefield, _ = _services()
    location = world.location("青溪村")

    by_name = battlefield.surface("青溪村")
    by_xy = battlefield.surface((location.coordinate.x, location.coordinate.y))

    assert by_name == by_xy
    assert by_name.coordinate == (8, 8)
    assert by_name.altitude == 2360
    assert by_name.terrain == "溪谷"
    assert battlefield.status().surface_terrain_count == 54


def test_every_terrain_owns_one_json_document() -> None:
    root = Path(__file__).resolve().parents[1] / "data" / "内容" / "战场环境"
    documents = sorted(root.glob("*.json"))

    assert len(documents) == 55
    for path in documents:
        values = json.loads(path.read_text(encoding="utf-8"))
        assert len(values) == 1
        assert values[0]["名称"] == path.stem


def test_default_realm_is_effectless_and_has_no_surface_coordinate() -> None:
    data, _, battlefield, combat = _services()
    field = battlefield.realm("未知秘境")
    environment = data.entity("战场环境", field.environment_id)

    assert field.environment_id == "610001"
    assert field.coordinate is None
    assert field.altitude is None
    assert environment["名称"] == "无相境"
    assert len(environment["阶段"]) == 1
    realm_stage = environment["阶段"][0]
    assert realm_stage["名称"] == "寂然无相"
    assert realm_stage["起始承伤比例"] == 0
    assert not realm_stage["入阶能力"]
    assert not realm_stage["常驻能力"]

    result = asyncio.run(
        combat.execute(
            CombatRequest(
                left_team=(_combatant("甲", attack=20),),
                right_team=(_combatant("乙", attack=20),),
                seed=1,
                action_limit=1,
                field=field,
            )
        )
    )
    assert result.field is not None
    assert result.field.stage_index == 0
    assert result.field.coordinate is None
    assert not [event for event in result.events if event.source_id.startswith("战场环境:") and event.kind == "受到伤害后"]


def test_damage_crosses_stages_in_order_and_environment_damage_does_not_feed_back() -> None:
    _, _, battlefield, combat = _services()
    request = CombatRequest(
        left_team=(_combatant("甲", attack=6000, health=2000, shield=5000),),
        right_team=(_combatant("乙", attack=6000, health=2000, shield=5000),),
        seed=1,
        action_limit=1,
        field=battlefield.surface("青溪村"),
        report=CombatReportSpec(generated_at="2026-08-03T00:00:00+08:00"),
    )

    result = asyncio.run(combat.execute(request))

    assert result.field is not None
    assert result.field.health_basis == 4000
    assert result.field.accumulated_damage == 6000
    assert result.field.stage_index == 3
    changes = [event for event in result.events if event.kind == "地势变化后"]
    assert [event.values["新阶段"] for event in changes] == [
        "水雾绕石",
        "溪流急涨",
        "山溪冲谷",
    ]
    environment_damage = [
        event
        for event in result.events
        if event.kind == "受到伤害后"
        and event.source_id == "战场环境:610049"
    ]
    assert [event.amount for event in environment_damage] == [80]
    assert result.field.accumulated_damage == sum(
        event.amount
        for event in result.events
        if event.kind == "受到伤害后"
        and not event.source_id.startswith("战场环境:")
    )
    assert result.report is not None
    assert result.report["scene"] == "青溪村"
    assert result.report["field"] == {
        "environment_id": "610049",
        "name": "溪谷",
        "origin": "地表",
        "scene": "青溪村",
        "coordinate": {"x": 8, "y": 8},
        "altitude": 2360,
        "terrain": "溪谷",
        "stage_index": 3,
        "stage_name": "山溪冲谷",
        "accumulated_damage": 6000,
        "health_basis": 4000,
        "damage_ratio": 1.5,
        "stage_changes": [
            {
                "turn": 1,
                "from": previous,
                "to": current,
                "accumulated_damage": 6000,
                "damage_ratio": 1.5,
            }
            for previous, current in (
                ("溪声清浅", "水雾绕石"),
                ("水雾绕石", "溪流急涨"),
                ("溪流急涨", "山溪冲谷"),
            )
        ],
    }


def test_late_surface_stages_end_a_recovery_battle_sooner() -> None:
    _, _, battlefield, combat = _services()
    left = _combatant("甲", attack=100, health=1000, health_recovery=50)
    right = _combatant("乙", attack=100, health=1000, health_recovery=50)
    neutral = asyncio.run(
        combat.execute(
            CombatRequest(
                left_team=(left,),
                right_team=(right,),
                seed=7,
                action_limit=200,
            )
        )
    )
    surface = asyncio.run(
        combat.execute(
            CombatRequest(
                left_team=(left,),
                right_team=(right,),
                seed=7,
                action_limit=200,
                field=battlefield.surface("青溪村"),
            )
        )
    )

    assert neutral.draw is False
    assert surface.draw is False
    assert surface.actions < neutral.actions


def _combatant(
    identity: str,
    *,
    attack: float,
    health: float = 100,
    shield: float = 0,
    health_recovery: float = 0,
) -> CombatantSpec:
    return CombatantSpec(
        id=identity,
        name=identity,
        attributes={
            "血气上限": health,
            "精神上限": 100,
            "护盾上限": shield,
            "攻击": attack,
            "防御": 0,
            "速度": 100,
            "命中率": 100,
            "血气恢复": health_recovery,
        },
        shield=shield,
    )


@lru_cache(maxsize=1)
def _services() -> tuple[
    JsonDataService,
    WorldService,
    BattlefieldService,
    CombatService,
]:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    world = WorldService(data)
    world.initialize()
    battlefield = BattlefieldService(data, world)
    battlefield.initialize()
    combat = CombatService(data)
    combat.initialize()
    return data, world, battlefield, combat
