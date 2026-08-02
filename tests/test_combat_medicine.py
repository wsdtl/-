"""恢复丹的百分比效果必须由战斗核心按资源上限执行。"""

from __future__ import annotations

from pathlib import Path

from game.core.combat import CombatantSpec, CombatRequest, CombatService
from game.core.data import JsonDataService, materialize
from game.core.item import ItemService


def test_auto_medicine_uses_resource_maximum_for_percentage_recovery() -> None:
    data = JsonDataService(Path(__file__).resolve().parents[1] / "data")
    data.initialize()
    combat = CombatService(data)
    combat.initialize()
    items = ItemService(data)
    items.initialize()

    request = CombatRequest(
        left_team=(
            CombatantSpec(
                id="left",
                name="left",
                attributes={
                    "血气上限": 100,
                    "精神上限": 20,
                    "攻击": 10,
                    "防御": 1,
                    "速度": 100,
                    "命中率": 100,
                },
                health=5,
                inventory={"100006": 1},
                auto_medicine=True,
                medicine_threshold=0.5,
            ),
        ),
        right_team=(
            CombatantSpec(
                id="right",
                name="right",
                attributes={
                    "血气上限": 100,
                    "精神上限": 20,
                    "攻击": 0,
                    "防御": 100,
                    "速度": 1,
                    "命中率": 100,
                },
            ),
        ),
        seed=7,
        action_limit=1,
        medicine_definitions=items.medicines(("100006",)),
    )

    result = combat._execute_sync(request)

    assert result.left.health == 30
    assert result.left.consumed_items == {"100006": 1}
    assert materialize(data.entity("物品", "100006"))["使用效果"] == {
        "类型": "恢复血气",
        "恢复百分比": 25,
    }
