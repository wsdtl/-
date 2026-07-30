"""审查战斗方向是否拥有真实不同的能力树，而不是只替换名称。"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core import JsonDataReader


MECHANISM_DIR = ROOT / "data" / "内容" / "战斗机制" / "方向"
CHECKS_PATH = ROOT / "tools" / "战斗校验" / "内容完整性.json"
REPORT_PATH = ROOT / "log" / "战斗机制审查.json"

REQUIRED_COVERAGE = {
    "修改机制计量": 264,
    "修改蓄势进度": 1,
    "追加行动": 1,
    "分摊伤害": 1,
    "转移伤害": 1,
}
IGNORED_FIELDS = frozenset({"名称", "计量", "机制"})


def _normalized_scalar(field: str, value: Any) -> Any:
    if field == "状态" and isinstance(value, str):
        return "<状态>"
    if field == "标签" and isinstance(value, list):
        return sorted({str(item).partition(":")[0] for item in value})
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int | float):
        if value == 0:
            return "零"
        return "正" if value > 0 else "负"
    return value


def _normalize(field: str, value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, child in sorted(value.items()):
            if key in IGNORED_FIELDS:
                continue
            if key == "属性" and isinstance(child, dict):
                normalized[key] = {
                    str(attribute): _normalized_scalar(str(attribute), amount)
                    for attribute, amount in sorted(child.items())
                }
                continue
            normalized[key] = _normalize(str(key), child)
        return normalized
    if isinstance(value, list):
        if field == "标签":
            return _normalized_scalar(field, value)
        return [_normalize(field, child) for child in value]
    return _normalized_scalar(field, value)


def _walk_abilities(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        ability = value.get("能力")
        if isinstance(ability, str) and ability:
            result.append(ability)
        for child in value.values():
            result.extend(_walk_abilities(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_walk_abilities(child))
    return result


def audit() -> dict[str, Any]:
    checks = JsonDataReader(CHECKS_PATH.parent).read(CHECKS_PATH.name)
    expected_directions = int(checks["方向数量"])
    signatures: dict[str, str] = {}
    collisions: dict[str, list[str]] = defaultdict(list)
    coverage: Counter[str] = Counter()
    ability_totals: Counter[str] = Counter()

    for path in sorted(MECHANISM_DIR.glob("机制-*.json"), key=lambda item: item.name):
        direction = path.stem.removeprefix("机制-")
        data = json.loads(path.read_text(encoding="utf-8"))
        mechanisms = data
        if not isinstance(mechanisms, dict) or not mechanisms:
            raise ValueError(f"{path.name}缺少机制定义")
        normalized = [_normalize("机制", node) for node in mechanisms.values()]
        signature = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        signatures[direction] = signature
        collisions[signature].append(direction)
        abilities = Counter(_walk_abilities(mechanisms))
        ability_totals.update(abilities)
        for ability in abilities:
            coverage[ability] += 1

    duplicate_groups = [
        values for values in collisions.values() if len(values) > 1
    ]
    failures: list[str] = []
    if len(signatures) != expected_directions:
        failures.append(
            f"方向数量应为{expected_directions}，当前为{len(signatures)}"
        )
    if duplicate_groups:
        failures.append(f"存在{len(duplicate_groups)}组仅换名称的重复能力树")
    for ability, minimum in REQUIRED_COVERAGE.items():
        actual = coverage.get(ability, 0)
        if actual < minimum:
            failures.append(f"{ability}至少应覆盖{minimum}个方向，当前为{actual}")

    report = {
        "版本": "晓楠修仙.战斗机制审查.v1",
        "结论": "通过" if not failures else "拒绝",
        "摘要": {
            "方向数量": len(signatures),
            "去名后独立能力树": len(collisions),
            "重复组数量": len(duplicate_groups),
        },
        "核心能力覆盖方向数": {
            key: coverage.get(key, 0) for key in REQUIRED_COVERAGE
        },
        "核心能力节点总数": {
            key: ability_totals.get(key, 0) for key in REQUIRED_COVERAGE
        },
        "重复组": duplicate_groups,
        "问题": failures,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    report = audit()
    summary = report["摘要"]
    print(
        f"mechanics={report['结论']} directions={summary['方向数量']} "
        f"unique={summary['去名后独立能力树']} duplicates={summary['重复组数量']}"
    )
    if report["结论"] != "通过":
        for issue in report["问题"]:
            print(issue)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
