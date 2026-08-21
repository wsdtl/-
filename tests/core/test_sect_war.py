from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import game.app as game_app
import game.core.sect_war.service as sect_war_service
from game.config import GameConfig, GameDatabaseConfig
from game.core.database import SharedEntityMutation, TransactionCommand
from game.core.location import LocationMoveCommand
from game.core.sect_war import SectWarError
from game.features.chuangjian_renwu import CreateCharacterRequest


def _run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setattr(
        game_app,
        "game_config",
        GameConfig(
            GameDatabaseConfig(
                tmp_path / "game.db",
                tmp_path / "runtime.db",
                5000,
            )
        ),
    )
    value = game_app.build_game_services()
    yield value
    value.core.database.close()


def _commit(services, user_id: str, request_id: str, operations) -> None:
    _run(
        services.core.database.commit(
            TransactionCommand(user_id, request_id, "测试准备", tuple(operations), {})
        )
    )


def _prepare_two_sects(services) -> tuple[tuple[int, int], tuple[int, int]]:
    create = services.features.chuangjian_renwu
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    _run(create.create(CreateCharacterRequest("qq-2", "create-2", "白川", "男")))
    origin = _run(services.core.location.current("qq-1")).xy
    alternate = (origin[0] + 1, origin[1]) if origin[0] < 99 else (origin[0] - 1, origin[1])
    _run(
        services.core.location.move(
            LocationMoveCommand("qq-2", "move-for-sect", origin, alternate)
        )
    )
    _run(services.features.zongmen.create("qq-1", "sect-1", "青云宗"))
    _run(services.features.zongmen.create("qq-2", "sect-2", "赤霄宗"))
    _run(
        services.core.location.move(
            LocationMoveCommand("qq-2", "move-to-war", alternate, origin)
        )
    )
    for user_id in ("qq-1", "qq-2"):
        gain = _run(
            services.core.character.plan_spirit_stone_change(user_id, delta=500)
        )
        _commit(services, user_id, f"seed-stones-{user_id}", (gain.operation,))
        member = _run(services.core.sect.membership(user_id))
        spend = _run(
            services.core.character.plan_spirit_stone_change(user_id, delta=-500)
        )
        deposit = _run(
            services.core.sect_assets.plan_spirit_stone_change(member.sect_id, 500)
        )
        _commit(
            services,
            user_id,
            f"deposit-stones-{user_id}",
            (spend.operation, deposit),
        )
        _run(
            services.features.zongmen_tongxing.assemble(
                user_id, f"assemble-{user_id}"
            )
        )
    return origin, alternate


def _vault_stones(services, user_id: str) -> int:
    return _run(services.core.sect_assets.lingcang(user_id)).spirit_stones


def test_expired_and_withdrawn_challenges_refund_wager(services) -> None:
    _prepare_two_sects(services)
    war = services.core.sect_war
    first = _run(war.challenge("qq-1", "赤霄宗", 100, "challenge-1"))
    assert _vault_stones(services, "qq-1") == 400

    record = _run(services.core.database.get_shared_entity("宗门战", first.war_id))
    value = dict(record.value)
    value["过期时间"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    _commit(
        services,
        "qq-1",
        "expire-first-war",
        (SharedEntityMutation("宗门战", first.war_id, value, record.version),),
    )

    second = _run(war.challenge("qq-1", "赤霄宗", 50, "challenge-2"))
    assert _vault_stones(services, "qq-1") == 450
    withdrawn = _run(war.withdraw("qq-1", "withdraw-2"))
    assert withdrawn.status == "已撤回"
    assert _vault_stones(services, "qq-1") == 500

    history = _run(war.history("qq-1"))
    assert history.total == 2
    assert {entry.status for entry in history.entries} == {"已过期", "已撤回"}
    assert second.war_id in {entry.war_id for entry in history.entries}


def test_full_sect_war_uses_combat_and_settles_once(services) -> None:
    _prepare_two_sects(services)
    war = services.core.sect_war
    created = _run(war.challenge("qq-1", "赤霄宗", 100, "challenge"))
    accepted = _run(war.accept("qq-2", "accept"))
    assert accepted.status == "备战"
    assert _vault_stones(services, "qq-1") == 400
    assert _vault_stones(services, "qq-2") == 400

    _run(war.lock("qq-1", "lock-left"))
    locked = _run(war.lock("qq-2", "lock-right"))
    assert locked.status == "已锁定"
    assert locked.attacker_count == locked.defender_count == 1
    assert _run(services.core.player_state.current("qq-1")).states["行为"].state_id == "520013"
    assert _run(services.core.player_state.current("qq-2")).states["行为"].state_id == "520013"

    started = _run(war.start("qq-1", "start"))
    assert started.status == "战斗中"
    assert started.report_id == created.war_id
    record = _run(services.core.database.get_shared_entity("宗门战", created.war_id))
    assert record.value["战报"]["schema"] == "晓楠修仙.战报.v1"
    assert record.value["战报展示"]

    value = dict(record.value)
    value["结束时间"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    _commit(
        services,
        "qq-1",
        "finish-war-clock",
        (SharedEntityMutation("宗门战", created.war_id, value, record.version),),
    )
    settled = _run(war.current("qq-2", "settle"))
    assert settled.status == "已结算"
    assert _vault_stones(services, "qq-1") + _vault_stones(services, "qq-2") == 980
    assert _run(services.core.player_state.current("qq-1")).states["行为"].state_id == "520001"
    assert _run(services.core.player_state.current("qq-2")).states["行为"].state_id == "520001"
    assert _run(war.history("qq-1")).entries[0].war_id == created.war_id

    replayed = _run(war.view("qq-1", created.war_id))
    assert replayed.status == "已结算"
    with pytest.raises(SectWarError, match="no_active"):
        _run(war.current("qq-1"))


def test_sect_war_lifecycle_and_settlement_survive_service_restart(
    services, monkeypatch
) -> None:
    _prepare_two_sects(services)
    war = services.core.sect_war
    created = _run(war.challenge("qq-1", "赤霄宗", 100, "challenge-restart"))
    _run(war.accept("qq-2", "accept-restart"))
    _run(war.lock("qq-1", "lock-left-restart"))
    _run(war.lock("qq-2", "lock-right-restart"))
    started = _run(war.start("qq-1", "start-restart"))
    services.core.database.close()

    restored = game_app.build_game_services()
    try:
        current = started.ends_at + timedelta(seconds=1)
        monkeypatch.setattr(sect_war_service, "_now", lambda: current)
        lifecycle = _run(restored.core.sect_war.lifecycle("qq-1"))
        assert lifecycle.activity_id == created.war_id
        assert lifecycle.phase == "ready"
        assert lifecycle.can_settle is True
        settled = _run(
            restored.core.sect_war.current("qq-1", "settle-after-restart")
        )
        assert settled.status == "已结算"
        assert _run(restored.core.player_state.current("qq-1")).states[
            "行为"
        ].state_id == "520001"
    finally:
        restored.core.database.close()
