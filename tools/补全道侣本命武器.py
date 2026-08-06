"""为世界道侣补齐可持久化的本命武器初始状态。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "内容" / "世界"

WEAPON_SUFFIXES = {
    "守土剑修": "剑",
    "清修术士": "法印",
    "巡山修士": "灵尺",
    "炼体行者": "臂铠",
    "护阵修士": "阵盘",
    "游方医者": "灵针",
}


def main() -> None:
    updated_files = 0
    updated_companions = 0
    seen_weapon_names: set[str] = set()

    for path in sorted(WORLD.rglob("*道侣.json")):
        companions = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for index, companion in enumerate(companions):
            weapon = companion.get("本命武器")
            expected_weapon = _weapon(companion)
            if weapon is None:
                weapon = expected_weapon
                companion = _insert_after(companion, "气机池", "本命武器", weapon)
                companions[index] = companion
                changed = True
                updated_companions += 1
            elif isinstance(weapon, dict) and weapon.get(
                "名称"
            ) == _legacy_generated_name(companion):
                weapon["名称"] = expected_weapon["名称"]
                changed = True
            _validate_weapon(companion, weapon)
            weapon_name = str(weapon["名称"])
            if weapon_name in seen_weapon_names:
                raise ValueError(f"本命武器名称重复：{weapon_name}")
            seen_weapon_names.add(weapon_name)

        if changed:
            path.write_text(
                json.dumps(companions, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            updated_files += 1

    print(f"道侣本命武器补全完成：{updated_companions} 名道侣，{updated_files} 个文件")


def _weapon(companion: dict[str, object]) -> dict[str, object]:
    name = str(companion.get("名称") or "").strip()
    identity = companion.get("身份")
    if not isinstance(identity, dict):
        raise TypeError(f"道侣身份必须是对象：{name or '<未命名>'}")
    title = str(identity.get("称号") or "").strip()
    suffix = WEAPON_SUFFIXES.get(title)
    if suffix is None:
        raise ValueError(f"未登记的道侣称号：{name} -> {title or '<空>'}")
    if len(name) != 3:
        raise ValueError(f"道侣名称必须是三个字才能生成个人武器名：{name}")
    level = companion.get("等级")
    if not isinstance(level, int) or isinstance(level, bool) or level < 1:
        raise ValueError(f"道侣等级非法：{name} -> {level!r}")
    return {
        "名称": f"{name}{suffix}",
        "等级": level,
        "经验": 0,
        "器律": [],
    }


def _legacy_generated_name(companion: dict[str, object]) -> str:
    name = str(companion.get("名称") or "").strip()
    identity = companion.get("身份")
    if not isinstance(identity, dict):
        return ""
    suffix = WEAPON_SUFFIXES.get(str(identity.get("称号") or "").strip(), "")
    return f"{name[1:]}{suffix}" if len(name) == 3 and suffix else ""


def _insert_after(
    source: dict[str, object],
    anchor: str,
    key: str,
    value: object,
) -> dict[str, object]:
    result: dict[str, object] = {}
    inserted = False
    for current_key, current_value in source.items():
        result[current_key] = current_value
        if current_key == anchor:
            result[key] = value
            inserted = True
    if not inserted:
        raise ValueError(f"道侣缺少字段：{anchor}")
    return result


def _validate_weapon(companion: dict[str, object], weapon: object) -> None:
    companion_name = str(companion.get("名称") or "<未命名>")
    if not isinstance(weapon, dict):
        raise TypeError(f"道侣本命武器必须是对象：{companion_name}")
    if set(weapon) != {"名称", "等级", "经验", "器律"}:
        raise ValueError(f"道侣本命武器字段不完整：{companion_name}")
    if not str(weapon["名称"]).strip():
        raise ValueError(f"道侣本命武器名称为空：{companion_name}")
    if weapon["等级"] != companion.get("等级"):
        raise ValueError(f"道侣初始武器等级必须显式等于初始人物等级：{companion_name}")
    if weapon["经验"] != 0:
        raise ValueError(f"道侣初始武器经验必须为零：{companion_name}")
    if weapon["器律"] != []:
        raise ValueError(f"一级道侣不得预装器律：{companion_name}")


if __name__ == "__main__":
    main()
