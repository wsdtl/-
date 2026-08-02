"""修士与灵兽共享角色结构，但保留各自的修炼强度。"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from game.core.data import JsonDataService

ROOT = Path(__file__).resolve().parents[1]


def test_cultivator_and_spirit_beast_rules_share_one_structure() -> None:
    cultivator = _read_role_rule("敌方修士")
    spirit_beast = _read_role_rule("灵兽")

    assert cultivator.keys() == spirit_beast.keys()
    assert len(cultivator["阶梯"]) == len(spirit_beast["阶梯"]) == 6

    for cultivator_tier, spirit_beast_tier in zip(
        cultivator["阶梯"], spirit_beast["阶梯"], strict=True
    ):
        assert cultivator_tier.keys() == spirit_beast_tier.keys()
        assert cultivator_tier["阶梯"] == spirit_beast_tier["阶梯"]
        assert cultivator_tier["等级范围"] == spirit_beast_tier["等级范围"]


def test_spirit_beast_build_progression_is_weaker_than_cultivators() -> None:
    cultivator_tiers = _read_role_rule("敌方修士")["阶梯"]
    spirit_beast_tiers = _read_role_rule("灵兽")["阶梯"]

    assert [_single_build_slot(tier) for tier in spirit_beast_tiers] == list(
        range(1, 7)
    )
    for cultivator_tier, spirit_beast_tier in zip(
        cultivator_tiers, spirit_beast_tiers, strict=True
    ):
        assert _single_build_slot(spirit_beast_tier) < _single_build_slot(
            cultivator_tier
        )


def test_role_growth_references_resolve_and_spirit_beasts_grow_more_slowly() -> None:
    cultivator_rule = _read_role_rule("敌方修士")
    spirit_beast_rule = _read_role_rule("灵兽")
    cultivator_growth = _read_role_rule(cultivator_rule["成长规则"])
    spirit_beast_growth = _read_role_rule(spirit_beast_rule["成长规则"])

    cultivator_per_level = cultivator_growth["属性成长"]["每级"]
    spirit_beast_per_level = spirit_beast_growth["属性成长"]["每级"]
    assert set(cultivator_per_level) == set(spirit_beast_per_level)
    assert all(
        0 < spirit_beast_per_level[field] <= cultivator_per_level[field]
        for field in cultivator_per_level
    )
    assert any(
        spirit_beast_per_level[field] < cultivator_per_level[field]
        for field in cultivator_per_level
    )
    assert spirit_beast_growth["经验"]["基础"] > cultivator_growth["经验"]["基础"]
    assert (
        spirit_beast_growth["经验"]["等级平方系数"]
        > cultivator_growth["经验"]["等级平方系数"]
    )


def test_all_spirit_beasts_use_shared_growth_plus_species_correction() -> None:
    spirit_beast_growth = _read_role_rule("灵兽修炼")["属性成长"]["每级"]
    spirit_beasts = [
        value
        for value in _data_service().entities("敌人").values()
        if value.get("角色规则") == "灵兽"
    ]

    assert len(spirit_beasts) == 122
    for spirit_beast in spirit_beasts:
        assert "每级成长" not in spirit_beast
        assert spirit_beast.get("属性覆盖", {}).get("精神上限") != 0

        correction = spirit_beast.get("每级成长修正", {})
        actual_growth = {
            field: round(spirit_beast_growth[field] + correction.get(field, 0), 10)
            for field in ("血气上限", "攻击", "防御")
        }
        assert 6 <= actual_growth["血气上限"] <= 10
        assert 0.4 <= actual_growth["攻击"] <= 1
        assert 0.4 <= actual_growth["防御"] <= 1


def _read_role_rule(name: str) -> Mapping[str, Any]:
    value = _data_service().dataset("角色规则").get(name)
    assert isinstance(value, Mapping), f"角色规则不存在：{name}"
    return value


def _single_build_slot(tier: Mapping[str, Any]) -> int:
    slots = tier["构筑位"]
    assert set(slots) == {"功法", "附魔", "宝石"}
    assert len(set(slots.values())) == 1
    return next(iter(slots.values()))


@lru_cache(maxsize=1)
def _data_service() -> JsonDataService:
    service = JsonDataService(ROOT / "data")
    service.initialize()
    return service
