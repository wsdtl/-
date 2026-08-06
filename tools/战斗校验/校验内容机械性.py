"""审查内容实体名称中的维护术语和批量模板痕迹。"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
CONTENT_DIR = BASE_DIR / "data" / "内容"

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
    "回放",
)


def iter_entities() -> list[tuple[Path, dict]]:
    entities: list[tuple[Path, dict]] = []
    for path in sorted(CONTENT_DIR.rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        values = value if isinstance(value, list) else [value]
        entities.extend((path, item) for item in values if isinstance(item, dict))
    return entities


def main() -> None:
    problems: list[str] = []
    by_directory: dict[str, list[str]] = {}
    for path, entity in iter_entities():
        name = entity.get("名称")
        if not isinstance(name, str):
            continue
        found = [term for term in MECHANICAL_TERMS if term in name]
        if found:
            by_directory.setdefault(path.parent.name, []).append(
                f"{path.relative_to(BASE_DIR)}: {entity.get('编号')} {name} -> {', '.join(found)}"
            )

    for directory, entries in sorted(by_directory.items()):
        problems.extend(entries)

    if problems:
        raise SystemExit("\n".join(problems))

    print("内容实体名称机械性审查通过：未发现维护术语")


if __name__ == "__main__":
    main()
