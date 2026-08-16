"""通信适配器的最小生命周期和命令注册契约。"""

from abc import ABC, abstractmethod
from collections.abc import Callable


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
    async def shutdown() -> None:
        """关闭适配器并清理资源。"""


class BaseMessageHandler(BaseAdapter):
    """消息处理器基类。

    这里的约束只作为消息型驱动器实现参考，不提供通用分发运行时。
    每个驱动器应该独立维护自己的 handler、dispatch、manager 和队列策略。

    业务回调可接收的公共上下文字段：
    - user_id: 触发消息的统一游戏用户编号。
    - message: command 模式下命令词之后的参数，其余模式为空。
    - manager: 当前驱动器的回复器。
    - cmd: 命令片段。
    - raw_message: 完整原始文本。
    - message_context: 显式消息上下文。
    - reply_target: 当前消息的默认回复目标。
    - adapter_capabilities: 当前驱动器公开能力。
    - match: regex 模式的完整消息命中对象，其余模式为 None。

    驱动器回复器统一实现：
        async def send(message, is_log=True, request_id=None) -> bool
    """

    @staticmethod
    @abstractmethod
    def fullmatch(*args, **kwargs) -> Callable:
        """注册完整消息回调。"""

    @staticmethod
    @abstractmethod
    def command(*args, **kwargs) -> Callable:
        """注册命令词加参数回调。"""

    @staticmethod
    @abstractmethod
    def regex(*args, **kwargs) -> Callable:
        """注册完整消息正则回调。"""

    @staticmethod
    @abstractmethod
    def unregister_module(module_name: str) -> None:
        """移除一个来源模块的全部回调。"""
