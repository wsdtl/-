from __future__ import annotations

from dataclasses import dataclass

from game.core.combat import CombatantSpec
from game.core.enemy import EnemyInstance, EnemyReward, EnemyStatus
from game.core.raid import RaidService


class _Data:
    def dataset(self, name):
        assert name == "玩法规则"
        return {"讨伐": {"行为状态": "520014", "持续秒数": 120, "战斗行动上限": 2400}}

    def entity(self, section, entity_id):
        assert (section, entity_id) == ("讨伐", "北境讨伐")
        return {
            "首领池": ["北境首领"],
            "辅助池": ["北境辅助"],
            "属从池": ["北境属从"],
            "奖励池": ["北境奖励"],
            "首领阶梯": "天灾",
            "辅助阶梯": "天灾",
            "属从阶梯": "镇域",
            "首领人数": [1, 1],
            "辅助人数": [1, 1],
            "属从人数": [2, 2],
        }


@dataclass
class _Enemy:
    calls: list[tuple[str, tuple[str, ...], int]]

    def status(self):
        return EnemyStatus(True, 0)

    def generate_category(
        self, *, section, pool_names, count, seed, instance_prefix, required_tier=None
    ):
        self.calls.append((section, pool_names, count, required_tier))
        return tuple(
            EnemyInstance(
                f"{section}{index}",
                CombatantSpec(
                    id=f"{instance_prefix}:{index}",
                    name=f"{section}{index}",
                    attributes={"血气上限": 100, "精神上限": 50},
                ),
                EnemyReward(0, 0, ()),
            )
            for index in range(1, count + 1)
        )


def _service():
    enemy = _Enemy([])
    service = RaidService(_Data(), enemy)
    service.initialize()
    return service, enemy


def test_single_group_raid_only_generates_boss_group():
    service, enemy = _service()
    result = service.generate(
        service.definition("北境讨伐"),
        ally_group_count=1,
        seed=1,
        instance_prefix="raid",
    )

    assert len(result.groups) == 1
    assert [call[0] for call in enemy.calls] == ["讨伐首领", "讨伐辅助"]
    assert [call[3] for call in enemy.calls] == ["天灾", "天灾"]
    assert [item.combatant.group_role for item in result.boss_group.combatants] == [
        "主战者",
        "辅助",
    ]
    assert len({item.combatant.group_id for item in result.boss_group.combatants}) == 1


def test_each_extra_ally_group_gets_an_independent_subordinate_group():
    service, enemy = _service()
    result = service.generate(
        service.definition("北境讨伐"),
        ally_group_count=3,
        seed=2,
        instance_prefix="raid",
    )

    assert len(result.groups) == 3
    assert len({group.group_id for group in result.groups}) == 3
    assert [len(group.combatants) for group in result.subordinate_groups] == [2, 2]
    assert [call[0] for call in enemy.calls].count("讨伐属从") == 2
    assert [call[3] for call in enemy.calls if call[0] == "讨伐属从"] == ["镇域", "镇域"]
    assert all(
        member.combatant.group_role == "主战者"
        for group in result.subordinate_groups
        for member in group.combatants
    )
