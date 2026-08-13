from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path

from game.core.asset import AssetService
from game.core.character import CharacterService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, StateMutation, TransactionCommand
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.najie import NajieFeature
from message import RenderedMessage, render_local_message

najie_command = import_module("game.cmd.通用.纳戒")


def _run(awaitable):
    return asyncio.run(awaitable)


def _services(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    world = WorldService(data)
    world.initialize()
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    character = CharacterService(data, database, player_state, location)
    character.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    assets = AssetService(data, database)
    assets.initialize()
    najie = NajieFeature(assets)
    najie.initialize()
    return data, database, create, assets, najie


def _render(message) -> RenderedMessage:
    rendered = render_local_message(message, markdown=False)
    assert isinstance(rendered, RenderedMessage)
    return rendered


def test_initial_assets_form_json_driven_najie_home(tmp_path: Path) -> None:
    _, _, create, assets, najie = _services(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))

    snapshot = _run(assets.snapshot("qq-1"))
    home = _run(najie.home("qq-1"))
    rendered = _render(najie_command._home_message(home))

    assert snapshot.page_limit == 50
    assert [category.name for category in snapshot.categories] == [
        "物品",
        "道藏",
        "器藏",
        "阵藏",
        "所学",
    ]
    assert {
        (entry.subcategory, entry.content_id, entry.grade_id, entry.quantity)
        for entry in snapshot.entries
    } == {
        ("恢复丹", "100002", "01", 2),
        ("恢复丹", "100005", "01", 3),
    }
    assert "晓楠修仙 · 纳戒" in rendered.content
    assert "恢复丹 2" in rendered.content


def test_owned_cultivation_stays_in_library_and_obeys_json_sorting(
    tmp_path: Path,
) -> None:
    _, database, create, _, najie = _services(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    cultivation = next(
        state
        for state in _run(database.list_for_user("qq-1"))
        if state.address.state_type == "cultivation"
    )
    _run(
        database.commit(
            TransactionCommand(
                user_id="qq-1",
                request_id="cultivation-1",
                business_type="测试道藏",
                operations=(
                    StateMutation(
                        "qq-1",
                        "cultivation_library",
                        "400002:01",
                        {"编号": "400002", "品级": "01"},
                        0,
                    ),
                    StateMutation(
                        "qq-1",
                        "cultivation_library",
                        "400001:05",
                        {"编号": "400001", "品级": "05"},
                        0,
                    ),
                    StateMutation(
                        "qq-1",
                        "cultivation_library",
                        "400003:05",
                        {"编号": "400003", "品级": "05"},
                        0,
                    ),
                    StateMutation(
                        "qq-1",
                        "cultivation",
                        "main",
                        {
                            "功法": [{"编号": "400002", "品级": "01"}],
                            "真意": [],
                            "气机": [],
                        },
                        cultivation.version,
                    ),
                ),
                payload={},
            )
        )
    )

    page = _run(najie.page("qq-1", "道藏", "功法"))

    assert [entry.content_id for entry in page.entries] == [
        "400002",
        "400001",
        "400003",
    ]
    assert page.entries[0].equipped_slots == ("功法1",)


def test_holy_formation_keeps_its_independent_material_investment(
    tmp_path: Path,
) -> None:
    _, database, _, _, najie = _services(tmp_path)
    _run(
        database.commit(
            TransactionCommand(
                user_id="qq-1",
                request_id="formation-1",
                business_type="测试炼制阵法",
                operations=(
                    StateMutation(
                        "qq-1",
                        "formation_reserve",
                        "formation-instance-1",
                        {
                            "阵法编号": "530001",
                            "品级": "05",
                            "投入": {
                                "灵矿": "5832",
                                "兽宝": "1944",
                                "灵植": "3888",
                            },
                        },
                        0,
                    ),
                ),
                payload={},
            )
        )
    )

    page = _run(najie.page("qq-1", "阵藏", "圣品阵法"))

    assert len(page.entries) == 1
    assert page.entries[0].material_total == 11664


def test_each_subcategory_pages_by_fifty_with_complete_navigation(
    tmp_path: Path,
) -> None:
    data, database, _, _, najie = _services(tmp_path)
    item_ids = data.number_category_members("灵植")[:51]
    _run(
        database.commit(
            TransactionCommand(
                user_id="qq-1",
                request_id="materials-1",
                business_type="测试取得灵植",
                operations=tuple(
                    StateMutation(
                        "qq-1",
                        "inventory",
                        f"{item_id}:01",
                        {"编号": item_id, "品级": "01", "数量": 1},
                        0,
                    )
                    for item_id in item_ids
                ),
                payload={},
            )
        )
    )

    first = _run(najie.page("qq-1", "物品", "灵植", 1))
    second = _run(najie.page("qq-1", "物品", "灵植", 2))
    overflow = _run(najie.page("qq-1", "物品", "灵植", 99))
    first_message = _render(najie_command._page_message(first))
    second_message = _render(najie_command._page_message(second))

    assert (len(first.entries), len(second.entries)) == (50, 1)
    assert overflow.page == 2
    assert tuple(action.data for action in first_message.actions) == (
        "纳戒 物品 灵植 2",
        "纳戒 物品",
        "纳戒",
    )
    assert tuple(action.data for action in second_message.actions) == (
        "纳戒 物品 灵植 1",
        "纳戒 物品",
        "纳戒",
    )
