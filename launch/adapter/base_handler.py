"""通信适配器的最小生命周期和命令注册契约。"""

from abc import ABC, abstractmethod
from typing import Callable


class BaseAdapter(ABC):
    """通信或外部系统适配器基类。

    当前运行时由注册表启用 QQ webhook 和本地驱动。新增通信方式时实现本基类，
    再通过 adapter.registry 登记；mount 只消费注册结果，不认识具体协议。
    """

    @staticmethod
    @abstractmethod
    async def run() -> None:
        """启动适配器或整理运行期索引。"""

    @staticmethod
    @abstractmethod
    async def dispatch(*args, **kwargs) -> None:
        """分发消息、事件或外部请求。"""

    @staticmethod
    @abstractmethod
    def handler(*args, **kwargs) -> Callable:
        """注册处理函数。"""

    @staticmethod
    @abstractmethod
    async def shutdown() -> None:
        """关闭适配器并清理资源。"""


class BaseMessageHandler(BaseAdapter):
    """消息处理器基类。

    这里的约束只作为消息型驱动器实现参考，不提供通用分发运行时。
    每个驱动器应该独立维护自己的 handler、dispatch、manager 和队列策略。

    业务回调可接收的公共上下文字段：
    - client_id: 触发消息的调用方身份。
    - message: 命令触发片段之后的文本。
    - manager: 当前驱动器的回复器。
    - cmd: 命令片段。
    - raw_message: 完整原始文本。
    - message_context: 显式消息上下文。
    - reply_target: 当前消息的默认回复目标。
    - adapter_capabilities: 当前驱动器公开能力。
    - match: 正则命中对象；精确命令时为 None。

    驱动器回复器必须兼容：
        async def send(message, client_id, is_log=True, request_id=None) -> bool
    """
