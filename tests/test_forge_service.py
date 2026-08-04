"""炼器 JSON、精确耗材、四孔覆炼与战斗装配。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pytest

from game.core.combat import CombatantSpec, CombatBuildRef, CombatRequest, CombatService
from game.core.data import JsonDataService
from game.core.forge import (
    DIRECT_MODE,
    SIDE_MODE,
    ForgeError,
    ForgeMaterial,
    ForgeRequest,
    ForgeService,
    WeaponState,
)
from game.core.item import ItemService

ROOT = Path(__file__).resolve().parents[1]


def test_forge_json_covers_every_formal_material_and_real_passive_mechanisms() -> None:
    data, _, forge = _services()
    rules = data.dataset("炼器规则")
    mineral_pools = {str(row["灵矿池"]) for row in rules["归脉"]}
    beast_pools = {str(row["兽宝池"]) for row in rules["归引"]}

    assert len(mineral_pools) == 54
    assert len(data.pool_members(tuple(sorted(mineral_pools)), "物品")) == 108
    assert len(beast_pools) == 122
    assert len(data.pool_members(tuple(sorted(beast_pools)), "物品")) == 366
    assert forge.status().law_count == 64
    assert forge.status().method_count == 32
    assert len({law.name for law in forge.laws()}) == 64
    assert len({law.mechanism_ids for law in forge.laws()}) == 64
    assert {str(row["兽脉"]) for row in rules["归引"]} == {
        vein for law in forge.laws() for vein in law.guide_veins
    }
    assert {law.tier for law in forge.laws()} == {
        "灵器",
        "法器",
        "法宝",
        "后天灵宝",
    }
    for law in forge.laws():
        method = forge.method(law.forge_method)
        tier = next(value for value in forge.tiers() if value.name == law.tier)
        assert method.tier == law.tier
        assert tier.minimum_mineral_slots <= method.slot_count <= tier.maximum_mineral_slots
        assert len(law.guide_veins) == tier.guide_count
        assert all(
            data.entity("机制", identity)["节点"]["能力"] == "监听事件"
            for identity in law.mechanism_ids
        )


def test_forge_consumes_two_or_three_guides_and_exact_direct_minerals() -> None:
    data, items, forge = _services()
    laws = {
        tier: next(value for value in forge.laws() if value.tier == tier)
        for tier in ("灵器", "法宝")
    }

    for tier_name, law in laws.items():
        request = _direct_request(data, items, forge, law.identity)
        plan = forge.plan(request)
        expected_guides = 2 if tier_name == "灵器" else 3

        assert len(plan.guides) == expected_guides
        assert len(plan.allocations) == forge.method(law.forge_method).slot_count
        assert {value.mode for value in plan.allocations} == {DIRECT_MODE}
        assert plan.weapon.laws[request.slot - 1] == law.identity


def test_forge_accepts_side_substitution_and_rejects_unused_minerals() -> None:
    data, items, forge = _services()
    law = next(value for value in forge.laws() if value.tier == "灵器")
    direct = _direct_request(data, items, forge, law.identity)
    side_request = _replace_one_with_side(data, items, forge, direct)

    plan = forge.plan(side_request)
    assert sum(value.mode == SIDE_MODE for value in plan.allocations) == 2

    used = {value.item_id for value in side_request.auxiliaries}
    extra = next(value.identity for value in items.items("灵矿") if value.identity not in used)
    with pytest.raises(ForgeError, match="不能满足铸法|未被铸法消耗"):
        forge.plan(
            ForgeRequest(
                law_id=side_request.law_id,
                slot=side_request.slot,
                weapon=side_request.weapon,
                guides=side_request.guides,
                auxiliaries=(*side_request.auxiliaries, ForgeMaterial(extra, "01")),
            )
        )


def test_forge_overwrites_one_slot_and_keeps_the_other_three() -> None:
    data, items, forge = _services()
    laws = tuple(value for value in forge.laws() if value.tier == "后天灵宝")[:2]
    existing = WeaponState(
        level=100,
        laws=(laws[0].identity, laws[0].identity, laws[0].identity, laws[0].identity),
    )
    request = _direct_request(data, items, forge, laws[1].identity, weapon=existing, slot=3)

    plan = forge.plan(request)

    assert plan.replaced_law_id == laws[0].identity
    assert plan.weapon.laws == (
        laws[0].identity,
        laws[0].identity,
        laws[1].identity,
        laws[0].identity,
    )


def test_weapon_progresses_independently_and_opens_slots_by_tier() -> None:
    _, _, forge = _services()
    weapon = forge.default_weapon()

    assert forge.weapon_profile(weapon).tier == "凡器"
    assert forge.weapon_profile(weapon).open_slots == 0
    advanced = forge.add_experience(weapon, forge.experience_needed(1))
    assert advanced.level == 2
    assert advanced.experience == 0
    assert forge.weapon_profile(WeaponState(level=11)).open_slots == 1
    assert forge.weapon_profile(WeaponState(level=76)).open_slots == 4


def test_combat_loads_equipped_law_as_a_passive_build_entity() -> None:
    data, _, forge = _services()
    combat = CombatService(data)
    combat.initialize()
    law = forge.laws()[0]
    request = CombatRequest(
        left_team=(
            _combatant(
                "left",
                build=(CombatBuildRef("器律", law.identity, born_order=1),),
            ),
        ),
        right_team=(_combatant("right"),),
        seed=31,
        action_limit=20,
    )

    result = asyncio.run(combat.execute(request))

    assert result.actions > 0
    assert result.left.id == "left"


def _direct_request(
    data: JsonDataService,
    items: ItemService,
    forge: ForgeService,
    law_id: str,
    *,
    weapon: WeaponState | None = None,
    slot: int = 1,
) -> ForgeRequest:
    law = forge.law(law_id)
    tier = next(value for value in forge.tiers() if value.name == law.tier)
    guide_pools: dict[str, list[str]] = defaultdict(list)
    for row in data.dataset("炼器规则")["归引"]:
        guide_pools[str(row["兽脉"])].append(str(row["兽宝池"]))
    guides = []
    used_guides: set[str] = set()
    for vein in law.guide_veins:
        identity = _unused_pool_member(data, guide_pools[vein], used_guides)
        used_guides.add(identity)
        guides.append(ForgeMaterial(identity, tier.minimum_guide_grade))
        assert items.item(identity).category == "兽宝"

    mineral_pools: dict[str, list[str]] = defaultdict(list)
    for row in data.dataset("炼器规则")["归脉"]:
        mineral_pools[str(row["本脉"])].append(str(row["灵矿池"]))
    auxiliaries = []
    used_minerals: set[str] = set()
    for requirement in forge.method(law.forge_method).requirements:
        for _ in range(requirement.count):
            identity = _unused_pool_member(
                data,
                mineral_pools[requirement.vein],
                used_minerals,
            )
            used_minerals.add(identity)
            auxiliaries.append(ForgeMaterial(identity, tier.minimum_mineral_grade))
            assert items.item(identity).category == "灵矿"
    return ForgeRequest(
        law_id=law_id,
        slot=slot,
        weapon=weapon or WeaponState(level=tier.minimum_level),
        guides=tuple(guides),
        auxiliaries=tuple(auxiliaries),
    )


def _replace_one_with_side(
    data: JsonDataService,
    items: ItemService,
    forge: ForgeService,
    request: ForgeRequest,
) -> ForgeRequest:
    law = forge.law(request.law_id)
    tier = next(value for value in forge.tiers() if value.name == law.tier)
    assignments = data.dataset("炼器规则")["归脉"]
    primary = {str(row["灵矿池"]): str(row["本脉"]) for row in assignments}
    target = forge.method(law.forge_method).requirements[0].vein
    auxiliaries = list(request.auxiliaries)
    removed = next(
        value
        for value in auxiliaries
        if primary[items.item(value.item_id).source_pool] == target
    )
    auxiliaries.remove(removed)
    used = {value.item_id for value in auxiliaries}
    side_pools = [
        str(row["灵矿池"])
        for row in assignments
        if row["旁脉"] == target and row["本脉"] != target
    ]
    side_ids = []
    for pool in side_pools:
        for identity in data.pool_members((pool,), "物品"):
            if identity not in used:
                side_ids.append(identity)
                used.add(identity)
            if len(side_ids) == 2:
                break
        if len(side_ids) == 2:
            break
    assert len(side_ids) == 2
    auxiliaries.extend(
        ForgeMaterial(identity, tier.minimum_mineral_grade) for identity in side_ids
    )
    return ForgeRequest(
        law_id=request.law_id,
        slot=request.slot,
        weapon=request.weapon,
        guides=request.guides,
        auxiliaries=tuple(auxiliaries),
    )


def _unused_pool_member(
    data: JsonDataService,
    pools: list[str],
    used: set[str],
) -> str:
    for pool in pools:
        for identity in data.pool_members((pool,), "物品"):
            if identity not in used:
                return identity
    raise AssertionError("正式数据没有足够的不重复材料")


def _combatant(
    identity: str,
    *,
    build: tuple[CombatBuildRef, ...] = (),
) -> CombatantSpec:
    return CombatantSpec(
        id=identity,
        name=identity,
        build=build,
        attributes={
            "血气上限": 100,
            "精神上限": 20,
            "攻击": 20,
            "防御": 5,
            "速度": 100,
            "命中率": 100,
        },
    )


@lru_cache(maxsize=1)
def _services() -> tuple[JsonDataService, ItemService, ForgeService]:
    data = JsonDataService(ROOT / "data")
    data.initialize()
    items = ItemService(data)
    items.initialize()
    forge = ForgeService(data, items)
    forge.initialize()
    return data, items, forge
