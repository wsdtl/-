"""手动审查命令组件目录与 scope 声明是否一致。"""

from __future__ import annotations

import sys
from collections.abc import Collection, Iterable
from pathlib import Path


class CommandLayoutError(ValueError):
    """命令文件未遵守目录分类规范。"""


def audit_command_layout(
    commands: Iterable[tuple[str, str, str]],
    *,
    scopes: Collection[str],
) -> tuple[tuple[str, str, str], ...]:
    """检查命令是否位于受管目录且 scope 与目录一致。"""

    entries = tuple(commands)
    violations: list[str] = []
    for command, scope, module in entries:
        expected = _scope_from_module(module, scopes)
        if expected is None:
            violations.append(f"命令来源不在受管目录：{command} -> {module}")
        elif scope != expected:
            violations.append(
                f"命令范围不一致：{command} 声明{scope}，目录应为{expected}"
            )
        if scope not in scopes:
            violations.append(f"命令范围无效：{command} -> {scope}")
    if violations:
        raise CommandLayoutError("命令目录审查失败：\n" + "\n".join(violations))
    return entries


def _scope_from_module(module: str, scopes: Collection[str]) -> str | None:
    parts = module.split(".")
    try:
        index = parts.index("cmd")
        candidate = parts[index + 1]
    except (ValueError, IndexError):
        return None
    return candidate if candidate in scopes else None


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    root_text = str(project_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    from game.cmd.command import COMMAND_SCOPES, registered_commands

    entries = audit_command_layout(
        registered_commands(),
        scopes=COMMAND_SCOPES,
    )
    print(f"命令目录审查通过：{len(entries)} 条命令")


if __name__ == "__main__":
    main()
