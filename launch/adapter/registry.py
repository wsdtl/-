"""通信驱动器注册表与公共回复路由器。

MessageHandler 把同一业务回调注册到所有启用驱动器；AdapterReplyManager 根据
当前 ContextVar 或显式 ReplyTarget 选择真实 manager。业务层无需判断协议。
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from fastapi import APIRouter

from launch.log import C, logger
from message import coerce_message

from .base_handler import BaseAdapter
from .context import SendRequest, current_message_context
from .depends import call_with_dependencies


_current_manager: ContextVar[Any | None] = ContextVar(
    "adapter_current_manager",
    default=None,
)


@dataclass(frozen=True)
class AdapterHttpMount:
    """驱动器可选的 HTTP 入口。"""

    path: str
    router: APIRouter


@dataclass(frozen=True)
class AdapterSpec:
    """一个可启用通信适配器的公共描述。"""

    name: str
    handler: type[BaseAdapter]
    manager: Any
    has_context: Callable[[], bool]
    http_mount: AdapterHttpMount | None = None


def available_adapter_specs() -> Dict[str, AdapterSpec]:
    """返回项目已接入的适配器清单。

    这里使用函数内导入，避免业务模块导入公共注册器时提前形成循环依赖。
    """

    from . import local, qq
    from .local.manager import current_event as current_local_event
    from .qq.manager import current_event

    return {
        "qq": AdapterSpec(
            name="qq",
            handler=qq.QqEventHandler,
            manager=qq.manager,
            has_context=lambda: current_event.get() is not None,
            http_mount=AdapterHttpMount(path=qq.QQ_EVENT_ROUTE, router=qq.router),
        ),
        "local": AdapterSpec(
            name="local",
            handler=local.LocalEventHandler,
            manager=local.manager,
            has_context=lambda: current_local_event.get() is not None,
        ),
    }


def enabled_adapter_names() -> List[str]:
    """返回当前运行时启用的适配器名称。"""

    return ["qq", "local"]


def enabled_adapter_specs() -> List[AdapterSpec]:
    """返回当前启用的适配器描述。"""

    available = available_adapter_specs()
    return [available[name] for name in enabled_adapter_names()]


class MessageHandler:
    """把业务命令同时注册到当前启用的消息适配器。"""

    @staticmethod
    def handler(*args, **kwargs) -> Callable:
        """把一个业务命令按相同规则注册到所有启用驱动器。"""

        def wrapper(func: Callable) -> Callable:
            for spec in enabled_adapter_specs():
                spec.handler.handler(*args, **kwargs)(
                    MessageHandler._bind_manager(func, spec.manager)
                )
            return func

        return wrapper

    @staticmethod
    def _bind_manager(func: Callable, real_manager: Any) -> Callable:
        async def wrapped(**context: Any) -> Any:
            token = _current_manager.set(context.get("manager") or real_manager)
            try:
                public_context = dict(context)
                public_context["manager"] = manager
                return await call_with_dependencies(func, public_context)
            finally:
                _current_manager.reset(token)

        return wrapped


class AdapterReplyManager:
    """根据当前消息上下文选择真实适配器回复器。"""

    async def send(
        self,
        message: object,
        client_id: str,
        is_log: bool = True,
        request_id: object | None = None,
    ) -> bool:
        """把回复转交当前或显式目标所属的真实驱动器。"""

        payload = message.message if isinstance(message, SendRequest) else message
        if coerce_message(payload) is None:
            raise TypeError(
                "公共 manager 只接受 message.Message；"
                "平台原生 payload 只能在对应驱动器内部使用"
            )

        manager = self._current_manager()
        if isinstance(message, SendRequest) and message.target is not None:
            manager = self._manager_for_adapter(message.target.adapter) or manager

        if manager is None:
            if is_log:
                logger.opt(colors=True).warning(
                    f"{C.warn('回复失败，缺少当前适配器上下文')} {C.kv('client', client_id)}"
                )
            return False

        return await manager.send(
            message,
            client_id,
            is_log=is_log,
            request_id=request_id,
        )

    @staticmethod
    def _current_manager() -> Any | None:
        current = _current_manager.get()
        if current is not None:
            return current

        message_context = current_message_context()
        if message_context is not None:
            manager = AdapterReplyManager._manager_for_adapter(message_context.adapter)
            if manager is not None:
                return manager

        for spec in enabled_adapter_specs():
            if spec.has_context():
                return spec.manager

        return None

    @staticmethod
    def _manager_for_adapter(adapter: str) -> Any | None:
        spec = available_adapter_specs().get(str(adapter or "").strip().lower())
        if spec is None:
            return None
        return spec.manager


manager = AdapterReplyManager()
