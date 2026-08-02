from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))

from game.core.data import JsonDataService, materialize

SPECS = (
    ("功法", 600),
    ("附魔", 600),
    ("宝石", 703),
)


def main() -> int:
    issues: list[str] = []
    records: list[tuple[str, str, dict[str, Any]]] = []
    data = JsonDataService(DATA)
    data.initialize()

    for kind, expected in SPECS:
        entities = data.entities(kind)
        count = len(entities)
        for identity in entities:
            record = data.entity_record(kind, identity)
            records.append((kind, record.source_file, materialize(record.value)))
        if count != expected:
            issues.append(f"{kind}实体数量应为 {expected}，实际为 {count}")

    names: dict[str, tuple[str, int, str]] = {}
    weights: dict[int, str] = {}
    for kind, source_file, value in records:
        identity = str(value.get("编号") or "")
        name = str(value.get("名称") or "")
        weight = value.get("权重")
        source = source_file
        if not identity or not name:
            issues.append(f"{source}：实体缺少编号或名称")
            continue
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
            issues.append(f"{source} -> {identity} {name}：权重必须是正整数")
            continue
        previous_name = names.get(name)
        signature = (
            identity,
            weight,
            json.dumps(value.get("能力"), ensure_ascii=False, sort_keys=True),
        )
        if previous_name is not None and previous_name != signature:
            issues.append(f"同名实体定义或权重不一致：{name}")
        else:
            names[name] = signature
        previous_weight = weights.get(weight)
        if previous_weight is not None and previous_weight != name:
            issues.append(f"异名实体权重重复：{previous_weight}、{name} -> {weight}")
        else:
            weights[weight] = name

    for identity, value in data.entities("道侣").items():
        if "权重" in value:
            issues.append(f"道侣 {identity}：城镇道侣不应保存权重")

    if issues:
        print("全池权重校验失败：")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print(f"全池权重校验通过：{len(records)} 个实体，{len(weights)} 个异名唯一权重")
    for kind, _ in SPECS:
        selected = [
            value["权重"] for record_kind, _, value in records if record_kind == kind
        ]
        print(f"- {kind}：{len(selected)}，{min(selected)}..{max(selected)}")
    print("- 城镇道侣：未保存权重")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
