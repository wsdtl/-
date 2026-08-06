"""按姓名倾向和地点平衡为世界道侣补齐固定性别。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "内容" / "世界"

GENDER_SCORE = {
    "景行": 3,
    "怀瑾": 3,
    "清和": 1,
    "长歌": 1,
    "云舒": 0,
    "知微": 0,
    "昭宁": -1,
    "听澜": -1,
    "星遥": -1,
    "明雪": -3,
    "若棠": -3,
}


@dataclass(frozen=True)
class Place:
    path: Path
    companions: list[dict[str, object]]
    lower_male_count: int
    extra_male_score: int


def main() -> None:
    places = [_load_place(path) for path in sorted(WORLD.rglob("*道侣.json"))]
    odd_places = [place for place in places if len(place.companions) % 2]
    male_majority_count = len(odd_places) // 2
    male_majority_paths = {
        place.path
        for place in sorted(
            odd_places,
            key=lambda value: (
                -value.extra_male_score,
                value.path.as_posix(),
            ),
        )[:male_majority_count]
    }

    updated_files = 0
    updated_companions = 0
    totals = {"男": 0, "女": 0}
    for place in places:
        male_count = place.lower_male_count + int(place.path in male_majority_paths)
        ordered = sorted(
            place.companions,
            key=lambda value: (
                -_score(value),
                str(value.get("编号") or ""),
            ),
        )
        male_ids = {str(value["编号"]) for value in ordered[:male_count]}
        changed = False
        for companion in place.companions:
            gender = "男" if str(companion.get("编号")) in male_ids else "女"
            totals[gender] += 1
            if companion.get("性别") == gender:
                continue
            if "性别" in companion:
                raise ValueError(
                    f"已有性别与分配规则冲突：{companion.get('名称')} -> {companion.get('性别')}"
                )
            _insert_after(companion, "名称", "性别", gender)
            changed = True
            updated_companions += 1
        if changed:
            place.path.write_text(
                json.dumps(place.companions, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            updated_files += 1

    if totals != {"男": 132, "女": 132}:
        raise ValueError(f"道侣性别没有严格对半：{totals}")
    print(
        f"道侣性别补全完成：{updated_companions} 名道侣，{updated_files} 个文件，"
        f"男 {totals['男']}，女 {totals['女']}"
    )


def _load_place(path: Path) -> Place:
    companions = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(companions, list) or not companions:
        raise ValueError(f"道侣文件必须是非空字典列表：{path}")
    ordered = sorted(
        companions,
        key=lambda value: (-_score(value), str(value.get("编号") or "")),
    )
    lower_male_count = len(companions) // 2
    extra_male_score = (
        _score(ordered[lower_male_count]) if len(companions) % 2 else -100
    )
    return Place(path, companions, lower_male_count, extra_male_score)


def _score(companion: dict[str, object]) -> int:
    name = str(companion.get("名称") or "")
    if len(name) != 3:
        raise ValueError(f"道侣名称必须是三个字：{name or '<空>'}")
    given_name = name[1:]
    if given_name not in GENDER_SCORE:
        raise ValueError(f"未登记的道侣名字：{name}")
    return GENDER_SCORE[given_name]


def _insert_after(
    source: dict[str, object],
    anchor: str,
    key: str,
    value: object,
) -> None:
    items = list(source.items())
    source.clear()
    inserted = False
    for current_key, current_value in items:
        source[current_key] = current_value
        if current_key == anchor:
            source[key] = value
            inserted = True
    if not inserted:
        raise ValueError(f"道侣缺少字段：{anchor}")


if __name__ == "__main__":
    main()
