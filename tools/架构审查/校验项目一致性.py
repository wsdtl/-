"""手动审查命令、帮助、按钮、组件目录与总说明是否一致。"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path


class ProjectConsistencyError(ValueError):
    """项目公开声明与真实代码不一致。"""


STALE_STATEMENTS = {
    "README.md": ("当前开放 `帮助`、`创建人物`、`人物`、`地图` 和 `查看物品` 五个玩家命令",),
    "data/规则/说明.md": ("宗门战尚未定义或实现",),
    "data/规则/玩法/说明.md": ("宗门战仍须单独设计",),
}


def audit_project_consistency(project_root: Path) -> tuple[int, int]:
    """返回公开命令数和按钮命令数；发现不一致时汇总报错。"""

    root = project_root.resolve()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    import game.cmd  # noqa: F401
    from game.cmd.command import COMMAND_SCOPES, registered_commands
    from game.cmd.help_registry import help_registry
    from tools.架构审查.校验命令目录 import audit_command_layout

    commands = audit_command_layout(registered_commands(), scopes=COMMAND_SCOPES)
    public = {command for command, scope, _ in commands if scope != "后台"}
    documented = {entry.command for entry in help_registry.entries()}
    errors: list[str] = []
    if public != documented:
        missing = sorted(public - documented)
        extra = sorted(documented - public)
        if missing:
            errors.append("玩家命令缺少帮助：" + "、".join(missing))
        if extra:
            errors.append("帮助没有对应命令：" + "、".join(extra))

    button_commands = tuple(_button_commands(root / "data" / "展示"))
    for source, command in button_commands:
        root_command = command.split(maxsplit=1)[0]
        if root_command not in public:
            errors.append(f"按钮命令未注册：{source} -> {command}")

    for base in (root / "game" / "core", root / "game" / "features", root / "game" / "cmd"):
        for directory in base.rglob("*"):
            if (
                directory.is_dir()
                and directory.name != "__pycache__"
                and not any(child.is_file() for child in directory.iterdir())
            ):
                errors.append(f"空组件目录：{directory.relative_to(root)}")

    for relative, statements in STALE_STATEMENTS.items():
        text = (root / relative).read_text(encoding="utf-8")
        for statement in statements:
            if statement in text:
                errors.append(f"陈旧说明：{relative} -> {statement}")

    if errors:
        raise ProjectConsistencyError("项目一致性审查失败：\n" + "\n".join(errors))
    return len(public), len(button_commands)


def _button_commands(root: Path) -> Iterable[tuple[str, str]]:
    for path in sorted(root.rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        for command in _commands(value):
            yield str(path.relative_to(root.parent.parent)), command


def _commands(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        command = value.get("命令")
        if isinstance(command, str) and command.strip():
            yield command.strip()
        for child in value.values():
            yield from _commands(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _commands(child)


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    command_count, button_count = audit_project_consistency(project_root)
    print(
        f"项目一致性审查通过：{command_count} 条玩家命令，"
        f"{button_count} 条按钮命令"
    )


if __name__ == "__main__":
    main()
