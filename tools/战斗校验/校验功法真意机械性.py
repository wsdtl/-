"""检查功法和真意是否退化为批量模板。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
TECHNIQUE_DIR = BASE_DIR / "data" / "内容" / "功法"
INSIGHT_DIR = BASE_DIR / "data" / "内容" / "真意"
MECHANICAL_TERMS = (
    "封判",
    "折返",
    "越界",
    "极境",
    "阵台",
    "末行动",
    "百行动",
    "全队",
    "群体",
    "全域",
    "冷却",
    "技能",
    "状态",
    "标签",
    "计量",
    "回放",
    "资源",
)
ROTATING_ENDINGS = "篆纹章契铭痕印魄"


def load_entities(directory: Path) -> list[dict]:
    result: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise TypeError(f"{path}必须使用字典列表")
        result.extend(value)
    return result


def move_suffix(technique: dict, ability: dict) -> str:
    prefix = f"{technique['名称']}·"
    name = str(ability["名称"])
    if not name.startswith(prefix):
        raise ValueError(f"{technique['编号']}的招式名未以功法名开头：{name}")
    return name[len(prefix) :]


def validate_techniques(values: list[dict]) -> list[str]:
    problems: list[str] = []
    suffixes: list[str] = []
    signatures: list[str] = []
    for item in values:
        current = [move_suffix(item, ability) for ability in item["能力"]]
        suffixes.extend(current)
        signatures.append("||".join(current))
        for name in current:
            terms = [term for term in MECHANICAL_TERMS if term in name]
            if terms:
                problems.append(
                    f"{item['编号']} {item['名称']}的招式{name}使用维护术语："
                    + "、".join(terms)
                )
    for name, count in Counter(suffixes).items():
        if count > 8:
            problems.append(f"功法招式后缀批量重复：{name} × {count}")
    for signature, count in Counter(signatures).items():
        if count > 4:
            problems.append(f"功法整套招式模板批量重复：{count} × {signature}")
    return problems


def validate_insights(values: list[dict]) -> list[str]:
    problems: list[str] = []
    ending_counts = Counter()
    for item in values:
        abilities = item.get("能力") or []
        if len(abilities) != 1 or abilities[0].get("能力") != "被动技能":
            problems.append(f"真意{item.get('编号')}必须只有一个被动技能")
            continue
        effects = abilities[0].get("效果") or []
        if len(effects) != 1 or effects[0].get("能力") != "引用被动机制":
            problems.append(f"真意{item.get('编号')}必须只引用一个被动机制")
        name = str(item.get("名称") or "")
        if abilities[0].get("名称") != name:
            problems.append(f"真意{item.get('编号')}的实体名与被动名不一致")
        if name[-1:] in ROTATING_ENDINGS:
            ending_counts[name[-1]] += 1
    for ending, count in ending_counts.items():
        if count > 15:
            problems.append(f"真意名称疑似轮换生成尾字：{ending} × {count}")
    return problems


def main() -> None:
    techniques = load_entities(TECHNIQUE_DIR)
    insights = load_entities(INSIGHT_DIR)
    problems = [
        *validate_techniques(techniques),
        *validate_insights(insights),
    ]
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"功法/真意机械性审查通过：{len(techniques)} 门功法，{len(insights)} 道真意")


if __name__ == "__main__":
    main()
