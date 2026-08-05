"""修士与灵兽共享角色结构，但保留各自的修炼强度。"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from game.core.data import JsonDataService
from game.core.forge import ForgeService
from game.core.item import ItemService
from game.core.role import RoleService

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
    assert (
        spirit_beast_growth["经验"]["幂次基数"]
        > cultivator_growth["经验"]["幂次基数"]
    )
    assert (
        spirit_beast_growth["经验"]["等级基数"]
        > cultivator_growth["经验"]["等级基数"]
    )
    assert spirit_beast_growth["经验"]["后段"] == cultivator_growth["经验"]["后段"]


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
        assert 0.06 <= actual_growth["攻击"] <= 0.12
        assert 0.4 <= actual_growth["防御"] <= 1


def test_growth_services_execute_the_declared_experience_curves() -> None:
    roles = _role_service()
    forge = _forge_service()

    assert roles.experience_needed("修士", 1) == 720
    assert roles.experience_needed("修士", 99) == 25_340_055
    assert roles.experience_needed("修士", 100) == 0
    assert roles.experience_needed("灵兽", 1) == 900
    assert sum(roles.experience_needed("修士", level) for level in range(1, 100)) == (
        351_398_872
    )

    assert forge.experience_needed(1) == 240
    assert forge.experience_needed(99) == 8_446_659
    assert sum(forge.experience_needed(level) for level in range(1, 100)) == 117_132_695


def test_enemy_rewards_follow_level_and_role_scale() -> None:
    enemies = _data_service().entities("敌人")

    assert len(enemies) == 160
    for enemy in enemies.values():
        lower, upper = enemy["等级"]
        assert enemy["交锋所得"]["人物经验"] == (
            80 + lower * 22,
            80 + upper * 22,
        )
        assert enemy["交锋所得"]["本命武器经验"] == (
            50 + lower * 5,
            80 + upper * 8,
        )
        reward_factor = 1 if enemy["角色规则"] == "灵兽" else 1.25
        assert enemy["掉落"]["灵石"] == (
            int((40 + lower * 12) * reward_factor + 0.5),
            int((80 + upper * 20) * reward_factor + 0.5),
        )


def test_item_reference_prices_use_the_shared_economic_unit() -> None:
    items = _item_service()

    assert len(items.items()) == 939
    expected_ranges = {
        "灵植": (220, 340),
        "灵矿": (340, 520),
        "兽宝": (340, 2300),
    }
    for category, expected in expected_ranges.items():
        prices = [item.reference_price for item in items.items(category)]
        assert (min(prices), max(prices)) == expected

    medicine_prices = [item.reference_price for item in items.items("丹药")]
    assert (min(medicine_prices), max(medicine_prices)) == (90, 1_800_000)


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


@lru_cache(maxsize=1)
def _item_service() -> ItemService:
    service = ItemService(_data_service())
    service.initialize()
    return service


@lru_cache(maxsize=1)
def _forge_service() -> ForgeService:
    service = ForgeService(_data_service(), _item_service())
    service.initialize()
    return service


@lru_cache(maxsize=1)
def _role_service() -> RoleService:
    service = RoleService(_data_service(), _item_service(), _forge_service())
    service.initialize()
    return service
