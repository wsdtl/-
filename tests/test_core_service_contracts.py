"""现有 JSON 核心微服务的公共请求与结果契约。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

from game.core.data import JsonDataError, JsonDataService
from game.core.pool import ALLOW_REPEATS, PoolRequest, PoolService


def test_pool_returns_stable_ids_instead_of_entity_definitions() -> None:
    data, pool = _services()
    file_id = next(
        Path(path).stem
        for path in data.document_paths()
        if Path(path).parent.as_posix() == "内容/功法"
    )

    result = pool.draw(
        PoolRequest(
            file_ids=(file_id,),
            section="功法",
            count=1,
            mode=ALLOW_REPEATS,
            seed=1001,
        )
    )

    assert len(result.entries) == 1
    assert result.entries[0].identity in data.entities("功法")
    assert not hasattr(result.entries[0], "definition")


def test_data_service_indexes_every_formal_content_and_pool() -> None:
    data, _ = _services()
    status = data.status()

    content_paths = tuple(
        path for path in data.document_paths() if path.startswith("内容/")
    )
    assert status.document_count == len(data.document_paths())
    assert status.content_document_count == len(content_paths)
    assert status.entity_count > 0
    assert status.pool_count > 0


def test_service_receives_named_dataset_instead_of_knowing_file_paths() -> None:
    data, _ = _services()

    definitions = data.dataset("战斗定义")
    rules = data.dataset("战斗规则")
    report = data.dataset("战斗展示")

    assert set(definitions) == {"属性", "资源", "事件", "原子能力"}
    assert set(rules) == {"伤害", "行动", "状态反应"}
    assert set(report) == {"战报"}


def test_source_pool_and_direct_identity_pool_both_expand() -> None:
    data, pool = _services()

    source_result = pool.draw(
        PoolRequest(
            file_ids=("入微敌方修士功法池",),
            section="功法",
            count=3,
            mode=ALLOW_REPEATS,
            seed=1001,
        )
    )
    direct_result = pool.draw(
        PoolRequest(
            file_ids=("500001-功法池",),
            section="功法",
            count=3,
            mode=ALLOW_REPEATS,
            seed=1001,
        )
    )

    assert source_result.candidate_count > 0
    assert direct_result.candidate_count > 0
    assert set(source_result.identities) <= set(data.entities("功法"))
    assert set(direct_result.identities) <= set(data.entities("功法"))


def test_pool_field_projection_does_not_copy_complete_entities() -> None:
    data, _ = _services()

    values = data.pool_fields(
        ("入微敌方修士宝石池",),
        "宝石",
        ("权重",),
    )

    assert len(values) == len(
        data.pool_members(("入微敌方修士宝石池",), "宝石")
    )
    assert all(set(fields) == {"权重"} for _, fields in values)


def test_pool_section_mismatch_is_rejected() -> None:
    data, _ = _services()

    with pytest.raises(JsonDataError, match="资源池集合不匹配"):
        data.pool_members(("入微敌方修士功法池",), "宝石")


def test_virtual_full_pool_uses_deduplicated_entity_index() -> None:
    data, pool = _services()

    result = pool.draw(
        PoolRequest(
            section="宝石",
            count=5,
            mode=ALLOW_REPEATS,
            full_pool=True,
            seed=1001,
        )
    )

    assert result.full_pool is True
    assert result.source_files == ()
    assert result.candidate_count == len(data.entities("宝石"))


def test_companion_collection_is_not_a_weighted_pool() -> None:
    data, pool = _services()

    companions = data.pool_members(("青溪村道侣",), "道侣")
    assert companions
    with pytest.raises(ValueError, match="不使用权重抽取"):
        pool.draw(
            PoolRequest(
                file_ids=("青溪村道侣",),
                section="道侣",
                count=1,
                mode=ALLOW_REPEATS,
                seed=1001,
            )
        )


@lru_cache(maxsize=1)
def _services() -> tuple[JsonDataService, PoolService]:
    root = Path(__file__).resolve().parents[1]
    data = JsonDataService(root / "data")
    data.initialize()
    pool = PoolService(data)
    pool.initialize()
    return data, pool
