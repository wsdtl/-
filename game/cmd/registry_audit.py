"""命令目录、scope 声明与帮助注册的一致性审查。"""

from __future__ import annotations

from collections.abc import Iterable

from .command import COMMAND_SCOPES, registered_commands


class CommandRegistryError(RuntimeError):
    """命令注册目录或声明不一致。"""


def audit_command_registry(
    commands: Iterable[tuple[str, str, str]] | None = None,
) -> tuple[tuple[str, str, str], ...]:
    """审查命令实际来源目录与显式 scope；通过后返回稳定注册快照。"""

    entries = tuple(commands if commands is not None else registered_commands())
    seen: dict[str, tuple[str, str]] = {}
    violations: list[str] = []
    for command, scope, module in entries:
        owner = seen.get(command.casefold())
        if owner is not None:
            violations.append(f"命令重复注册：{command} ({owner} / {scope}, {module})")
        seen[command.casefold()] = (scope, module)
        expected = _scope_from_module(module)
        if expected is None:
            violations.append(f"命令来源不在受管目录：{command} -> {module}")
        elif scope != expected:
            violations.append(
                f"命令范围不一致：{command} 声明{scope}，目录应为{expected}"
            )
        if scope not in COMMAND_SCOPES:
            violations.append(f"命令范围无效：{command} -> {scope}")
    if violations:
        raise CommandRegistryError("命令注册审查失败：\n" + "\n".join(violations))
    return entries


def _scope_from_module(module: str) -> str | None:
    parts = module.split(".")
    try:
        index = parts.index("cmd")
        return parts[index + 1] if parts[index + 1] in COMMAND_SCOPES else None
    except (ValueError, IndexError):
        return None


__all__ = ["CommandRegistryError", "audit_command_registry"]
