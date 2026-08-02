"""炼药 JSON 必须形成可替代、可扩展且引用闭合的正式数据。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from game.core.data import JsonDataService

VEINS = {"青华", "丹离", "坤载", "太白", "玄冥"}


def test_every_spirit_material_pool_is_assigned_to_two_distinct_veins() -> None:
    data = _data()
    assignments = data.dataset("炼药规则")["归脉"]
    declared_pools = [str(row["灵植池"]) for row in assignments]
    material_pools = {
        Path(path).stem
        for path in data.document_paths()
        if path.startswith("内容/物品/灵植/") and path.endswith(".json")
    }

    assert len(declared_pools) == len(set(declared_pools))
    assert set(declared_pools) == material_pools
    assert {str(row["本脉"]) for row in assignments} == VEINS
    assert all(
        row["本脉"] in VEINS
        and row["旁脉"] in VEINS
        and row["本脉"] != row["旁脉"]
        for row in assignments
    )

    material_ids = data.pool_members(tuple(sorted(material_pools)), "物品")
    assert len(material_ids) == 108
    assert all(
        data.entity_record("物品", identity).number_category == "灵植"
        for identity in material_ids
    )

    mineral_pools = {
        Path(path).stem
        for path in data.document_paths()
        if path.startswith("内容/物品/灵矿/") and path.endswith(".json")
    }
    mineral_ids = data.pool_members(tuple(sorted(mineral_pools)), "物品")
    assert len(mineral_pools) == 54
    assert len(mineral_ids) == 108
    assert all(
        data.entity_record("物品", identity).number_category == "灵矿"
        for identity in mineral_ids
    )


def test_every_beast_treasure_is_available_as_an_alchemy_guide() -> None:
    data = _data()
    guide_ids = set(data.pool_members(("药引-兽宝",), "物品"))
    beast_ids = {
        identity
        for identity in data.entities("物品")
        if data.entity_record("物品", identity).number_category == "兽宝"
    }

    assert len(guide_ids) == 366
    assert guide_ids == beast_ids


def test_battle_prescriptions_reference_furnace_methods_and_real_pills() -> None:
    data = _data()
    alchemy_rules = data.dataset("炼药规则")
    furnace_methods = {
        str(method["名称"]): method for method in alchemy_rules["炉法"]
    }
    strength_rules = {
        int(rule["强度"]): rule for rule in alchemy_rules["战丹"]["强度规则"]
    }
    difficulty_rules = {
        int(rule["炼制难度"]): rule
        for rule in alchemy_rules["战丹"]["炼制难度规则"]
    }
    assert alchemy_rules["丹则"]["战丹"]["同丹重复"] == "禁止"
    assert int(alchemy_rules["丹则"]["战丹"]["丹位上限"]) == 3
    prescriptions = data.entities("丹方")
    battle_attributes = set(data.dataset("战斗定义")["属性"])
    mechanism_ids = set(data.entities("机制"))
    output_ids: set[str] = set()
    mechanism_pill_ids: set[str] = set()
    compound_pill_ids: set[str] = set()

    assert len(prescriptions) == 160
    assert set(furnace_methods) == {
        str(prescription["炉法"]) for prescription in prescriptions.values()
    }
    for prescription in prescriptions.values():
        assert prescription["药引池"] == "药引-兽宝"
        output_id = str(prescription["成丹"])
        output_ids.add(output_id)
        assert data.entity_record("物品", output_id).number_category == "丹药"

        pill = data.entity("物品", output_id)
        effect = pill["使用效果"]
        status = effect["战前状态"]
        referenced_mechanisms = set(effect.get("战斗机制", ()))
        strength = int(pill["强度"])
        difficulty = int(prescription["炼制难度"])
        strength_rule = strength_rules[strength]
        difficulty_rule = difficulty_rules[difficulty]
        furnace = furnace_methods[str(prescription["炉法"])]
        ingredient_count = sum(int(row["味数"]) for row in furnace["辅材"])

        assert effect["类型"] == "寄存战丹"
        assert "丹位" not in pill
        assert int(strength_rule["丹位"]) > 0
        assert int(prescription["强度"]) == strength
        assert difficulty in {
            int(value) for value in strength_rule["允许炼制难度"]
        }
        assert int(difficulty_rule["辅材总味数"]["最少"]) <= ingredient_count
        assert ingredient_count <= int(difficulty_rule["辅材总味数"]["最多"])
        assert "最低药引品级" not in prescription
        assert "最低辅材品级" not in prescription
        assert difficulty_rule["最低药引品级"]
        assert difficulty_rule["最低辅材品级"]
        assert referenced_mechanisms <= mechanism_ids
        if referenced_mechanisms:
            mechanism_pill_ids.add(output_id)
            assert all(
                data.entity("机制", identity)["节点"]["能力"] == "监听事件"
                for identity in referenced_mechanisms
            )
        if int(output_id) >= 100087:
            compound_pill_ids.add(output_id)
            assert 2 <= len(referenced_mechanisms) <= 3
        assert status["持续单位"] == "整场战斗"
        assert set(status["属性"]) <= battle_attributes

    ingredient_counts = {
        sum(int(row["味数"]) for row in method["辅材"])
        for method in furnace_methods.values()
    }
    used_veins = {
        str(row["药脉"])
        for method in furnace_methods.values()
        for row in method["辅材"]
    }
    assert len(output_ids) == len(prescriptions)
    assert len(mechanism_pill_ids) == 148
    assert len(compound_pill_ids) == 80
    battle_pill_ids = {
        identity
        for identity, item in data.entities("物品").items()
        if item.get("使用效果", {}).get("类型") == "寄存战丹"
    }
    assert output_ids == battle_pill_ids
    battle_pill_weights = [
        int(data.entity("物品", identity)["权重"])
        for identity in battle_pill_ids
    ]
    assert len(battle_pill_weights) == len(set(battle_pill_weights))
    assert max(ingredient_counts) > min(ingredient_counts)
    assert used_veins == VEINS


def test_beast_treasure_names_are_short_unique_display_names() -> None:
    data = _data()
    names: list[str] = []
    for identity in data.entities("物品"):
        record = data.entity_record("物品", identity)
        if record.number_category != "兽宝":
            continue
        name = str(record.value["名称"])
        beast = record.source_file.removeprefix("兽宝-")
        assert not name.startswith(beast)
        names.append(name)

    assert len(names) == 366
    assert len(names) == len(set(names))


@lru_cache(maxsize=1)
def _data() -> JsonDataService:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    return data
