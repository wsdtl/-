from __future__ import annotations

from pathlib import Path

from game.core.combat.catalog import BattleReportCatalog
from game.core.combat.presentation import build_battle_report_presentation
from game.core.data import JsonDataService, materialize

PROJECT_ROOT = Path(__file__).parents[2]


def _catalog() -> BattleReportCatalog:
    data = JsonDataService(PROJECT_ROOT / "data")
    data.initialize()
    dataset = materialize(data.dataset("战斗展示"))
    return BattleReportCatalog.from_mapping(dataset["战报"])


def _participant(participant_id: str, name: str, number: int) -> dict[str, object]:
    return {
        "id": participant_id,
        "number": number,
        "name": name,
        "title": "修士",
        "level": 5,
        "combatant_type": "修士",
        "color": "#df3654" if number == 1 else "#008f75",
        "resources": [
            {
                "id": "health",
                "label": "血气",
                "current": 75,
                "maximum": 100,
                "display": "75 / 100",
                "percent": 75,
                "color": "#d63c50",
            }
        ],
        "initial_resources": {"health": 100, "spirit": 0, "shield": 0},
        "totals": [],
        "attributes": [],
        "techniques": [],
        "moves": [],
        "mechanisms": [],
        "statuses": [],
        "initial_statuses": [],
        "extra": {},
    }


def test_battle_report_json_uses_chinese_authoring_fields() -> None:
    catalog = _catalog()
    raw = catalog.raw

    assert raw["协议"]["展示版本"] == 4
    assert set(raw["展示"]["界面"]) == {
        "文案",
        "模式",
        "快照",
        "默认模式",
        "默认筛选",
        "默认快照",
    }
    assert "text" not in raw["展示"]["界面"]
    assert "filters" not in raw["展示"]["界面"]
    assert all("标识" in value and "名称" in value for value in raw["标准化"]["分类"])


def test_backend_presentation_is_complete_and_display_ready() -> None:
    catalog = _catalog()
    report = {
        "schema": catalog.report_schema,
        "generated_at": "2026-08-09T12:34:56+08:00",
        "scene": "溪隐台",
        "headline": "林远 对阵 白芷",
        "system": dict(catalog.system),
        "result": {
            "code": "victory",
            "title": "林远取胜",
            "actions": 7,
            "event_count": 0,
            "trigger_count": 0,
        },
        "participants": [
            _participant("player", "林远", 1),
            _participant("opponent", "白芷", 2),
        ],
        "events": [],
    }

    presentation, bundle = build_battle_report_presentation(report, catalog)

    assert presentation["version"] == 4
    assert presentation["document_title"] == "晓楠修仙 · 林远 对阵 白芷"
    assert presentation["time_label"] == "2026年08月09日 12:34:56"
    assert presentation["ui"]["defaults"] == {
        "mode": "compact",
        "filter": "all",
        "snapshot": "after",
    }
    assert presentation["detail"]["segments"][0]["final_participants"][0]["gauges"][0][
        "fill_percent"
    ] == 75
    assert "raw" not in bundle
    assert [value["id"] for value in presentation["ui"]["filters"]] == [
        "all",
        "damage",
        "status",
        "recover",
        "action",
    ]


def test_web_does_not_define_battle_display_content() -> None:
    sources = "\n".join(
        (PROJECT_ROOT / "static" / "battle-report" / name).read_text(encoding="utf-8")
        for name in ("index.html", "app.js", "timeline.js", "ui.js")
    )

    for forbidden in (
        '"万象行纪"',
        "晓楠修仙 · 交锋记录",
        "内容读取中",
        'data-mode="compact"',
        '"正在读取全部事件"',
        '"正在读取参战者状态"',
        '"状态对比读取中"',
        '"VS"',
        "raw_data_label",
        "renderRawDataAccess",
        "Intl.DateTimeFormat",
    ):
        assert forbidden not in sources
