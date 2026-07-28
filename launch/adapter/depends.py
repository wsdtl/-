"""命令回调的轻量依赖注入器。

解析器按函数签名注入公共上下文和 Depends，单条消息内可缓存依赖结果。组件
依赖不得隐藏驱动器私有 Depends，协议依赖必须直接出现在命令入口签名中。
"""

from __future__ import annotations

import inspect
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Tuple

from .context import current_message_context, current_reply_target


_current_message_context: ContextVar[dict[str, Any]] = ContextVar(
    "adapter_current_message_context",
    default={},
)


@dataclass(frozen=True)
class Depends:
    """声明一个命令参数由依赖函数计算得到。"""

    dependency: Callable
    use_cache: bool = True


class DependencyContext:
    """单条消息内的依赖解析上下文。"""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self.values = dict(values)
        self.cache: Dict[Callable, Any] = {}


async def call_with_dependencies(func: Callable, context: Mapping[str, Any]) -> Any:
    """按函数签名解析参数，支持普通上下文字段和 Depends。"""

    values = _expanded_context(context)
    dependency_context = DependencyContext(values)
    token = _current_message_context.set(values)
    try:
        kwargs = await resolve_kwargs(func, dependency_context)
        result = func(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
    finally:
        _current_message_context.reset(token)


def current_context_value(name: str, default: Any = None) -> Any:
    """读取当前消息上下文中的字段。"""

    return _current_message_context.get().get(name, default)


def _expanded_context(values: Mapping[str, Any]) -> dict[str, Any]:
    """同时提供聚合消息对象和常用公共字段。"""

    context = dict(values)
    message_context = context.get("message_context") or current_message_context()
    if message_context is not None:
        context.setdefault("message_context", message_context)
        context.setdefault("reply_target", message_context.reply_target)
        context.setdefault("adapter_capabilities", message_context.capabilities)
        context.setdefault("message_identity", message_context.identity)
    else:
        reply_target = context.get("reply_target") or current_reply_target()
        if reply_target is not None:
            context.setdefault("reply_target", reply_target)
    return context


async def resolve_kwargs(func: Callable, dependency_context: DependencyContext) -> dict[str, Any]:
    """为命令回调解析可注入参数，缺少必填参数时立即报错。"""

    signature = inspect.signature(func)
    kwargs: dict[str, Any] = {}

    for name, parameter in signature.parameters.items():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            kwargs.update(dependency_context.values)
            continue

        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue

        default = parameter.default
        if isinstance(default, Depends):
            kwargs[name] = await resolve_dependency(default, dependency_context)
            continue

        if name in dependency_context.values:
            kwargs[name] = dependency_context.values[name]
            continue

        if default is inspect.Parameter.empty:
            raise TypeError(f"缺少命令参数：{name}")

    return kwargs


async def resolve_dependency(
    depends: Depends,
    dependency_context: DependencyContext,
    stack: Tuple[Callable, ...] = (),
) -> Any:
    """递归解析一个 Depends，并执行循环与协议边界检查。"""

    dependency = depends.dependency
    if dependency in stack:
        raise RuntimeError(f"循环依赖：{dependency!r}")
    _assert_dependency_boundary(dependency, stack)
    if depends.use_cache and dependency in dependency_context.cache:
        return dependency_context.cache[dependency]

    kwargs = await resolve_dependency_kwargs(
        dependency,
        dependency_context,
        stack + (dependency,),
    )
    result = dependency(**kwargs)
    if inspect.isawaitable(result):
        result = await result

    if depends.use_cache:
        dependency_context.cache[dependency] = result
    return result


async def resolve_dependency_kwargs(
    dependency: Callable,
    dependency_context: DependencyContext,
    stack: Tuple[Callable, ...] = (),
) -> dict[str, Any]:
    """为依赖函数解析参数；规则与命令回调保持一致。"""

    signature = inspect.signature(dependency)
    kwargs: dict[str, Any] = {}

    for name, parameter in signature.parameters.items():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            kwargs.update(dependency_context.values)
            continue

        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue

        default = parameter.default
        if isinstance(default, Depends):
            kwargs[name] = await resolve_dependency(default, dependency_context, stack)
            continue

        if name in dependency_context.values:
            kwargs[name] = dependency_context.values[name]
            continue

        if default is inspect.Parameter.empty:
            raise TypeError(f"缺少依赖参数：{dependency.__name__}.{name}")

    return kwargs


def _assert_dependency_boundary(dependency: Callable, stack: Tuple[Callable, ...]) -> None:
    """禁止组件依赖函数把驱动器私有依赖藏进内部。"""

    if not stack or not _is_adapter_private_dependency(dependency):
        return

    parent = next((item for item in reversed(stack) if _is_component_dependency(item)), None)
    if parent is None:
        return

    raise RuntimeError(
        "组件 Depends 不能嵌套驱动器私有 Depends："
        f"{_callable_label(parent)} -> {_callable_label(dependency)}；"
        "请在命令函数签名里显式声明驱动器 Depends"
    )


def _is_component_dependency(func: Callable) -> bool:
    """判断依赖函数是否属于组件层。"""

    module = _callable_module(func)
    return bool(module) and not module.startswith("launch.")


def _is_adapter_private_dependency(func: Callable) -> bool:
    """判断依赖函数是否属于某个驱动器私有依赖模块。"""

    module = _callable_module(func)
    parts = module.split(".")
    return len(parts) >= 4 and parts[0] == "launch" and parts[1] == "adapter" and parts[-1] == "depends"


def _callable_module(func: Callable) -> str:
    """读取函数真实模块名，兼容被装饰过的函数。"""

    try:
        func = inspect.unwrap(func)
    except ValueError:
        pass
    return str(getattr(func, "__module__", "") or "")


def _callable_label(func: Callable) -> str:
    """生成依赖函数的错误提示名。"""

    module = _callable_module(func)
    name = str(getattr(func, "__qualname__", None) or getattr(func, "__name__", repr(func)))
    return f"{module}.{name}" if module else name
