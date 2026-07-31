from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
ITEMS = DATA / "内容" / "物品"
SPECS = (
    ("功法", ITEMS / "功法", "功法-*.json", 600),
    ("附魔", ITEMS / "附魔技能书", "物品-附魔-*.json", 600),
    ("宝石", ITEMS / "宝石", "物品-宝石-*.json", 703),
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    issues: list[str] = []
    records: list[tuple[str, Path, dict[str, Any]]] = []

    for kind, directory, pattern, expected in SPECS:
        count = 0
        for path in sorted(directory.glob(pattern)):
            values = read_json(path)
            if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
                issues.append(f"{path.relative_to(ROOT)}：实体源池必须是字典列表")
                continue
            count += len(values)
            records.extend((kind, path, value) for value in values)
        if count != expected:
            issues.append(f"{kind}实体数量应为 {expected}，实际为 {count}")

    names: dict[str, tuple[str, int, str]] = {}
    weights: dict[int, str] = {}
    for kind, path, value in records:
        identity = str(value.get("编号") or "")
        name = str(value.get("名称") or "")
        weight = value.get("权重")
        source = path.relative_to(ROOT).as_posix()
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

    for path in sorted((DATA / "内容" / "世界").rglob("*道侣.json")):
        for value in read_json(path):
            if isinstance(value, dict) and "权重" in value:
                issues.append(
                    f"{path.relative_to(ROOT)} -> {value.get('名称', '<未命名>')}："
                    "城镇道侣不应保存权重"
                )

    if issues:
        print("全池权重校验失败：")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print(f"全池权重校验通过：{len(records)} 个实体，{len(weights)} 个异名唯一权重")
    for kind, _, _, _ in SPECS:
        selected = [
            value["权重"]
            for record_kind, _, value in records
            if record_kind == kind
        ]
        print(f"- {kind}：{len(selected)}，{min(selected)}..{max(selected)}")
    print("- 城镇道侣：未保存权重")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
