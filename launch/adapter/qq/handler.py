"""QQ webhook 事件调度器。

本文件是 QQ 驱动器的中枢：接收已经解析出的消息事件，做事件去重、
后台排队、命令匹配、Depends 参数注入和业务函数调用。这里不直接
拼 OpenAPI 请求，也不关心 HTTP request 读取细节。
"""

import asyncio
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, Tuple, Union

from launch.config import config
from launch.log import C, logger
from launch.message_events import emit_message_event, event_from_incoming

from ..base_handler import BaseAdapter
from ..command_guard import CommandGuardContext, run_command_guards
from ..context import (
    AdapterCapabilities,
    CONVERSATION_GROUP,
    CONVERSATION_PRIVATE,
    MessageContext,
    ReplyTarget,
    reset_current_message_context,
    set_current_message_context,
)
from ..depends import call_with_dependencies
from .client import client
from .event import QqMessageEvent, parse_message_event, qq_message_identity
from .manager import current_event, manager
from .signature import make_validation_signature


Command = Union[str, Pattern]
ACK_RESPONSE = {"op": 12}


@dataclass(frozen=True)
class QqCommandRule:
    """QQ 命令注册规则。

    这个对象只描述“什么业务函数可以处理什么命令”，不保存任何
    QQ 会话状态。会话状态来自本次 webhook 解析出的 QqMessageEvent。
    """

    func: Callable
    priority: int
    block: bool
    order: int
    pattern: Optional[Pattern] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QqCommandMatch:
    """一条 QQ 消息命中命令后的临时结果。

    command 是本次消息触发的命令片段；message 是命令后面留给业务的
    参数文本。正则命令会额外带上 match，方便少数高级命令读取分组。
    """

    rule: QqCommandRule
    command: str
    message: str
    match: Optional[re.Match] = None


class QqEventHandler(BaseAdapter):
    """QQ 开放平台 webhook 驱动器。

    QQ 的通信流从开放平台事件回调开始：平台把事件 POST 到本地接口，
    本地必须尽快返回 ACK，真正的业务命令处理放到后台任务里执行。
    业务层仍然只看到统一的 client_id、message、manager 和 Depends 参数。
    """

    EVENT_WORKERS = 32
    MAX_WAITING_EVENTS = 1000
    USER_MAX_WAITING_EVENTS = 5
    EVENT_TASK_TIMEOUT = 9.0
    EVENT_ID_TTL_SECONDS = 120.0
    MAX_SEEN_EVENT_IDS = 3000
    INTERACTION_ACK_WORKERS = 4
    MAX_WAITING_INTERACTIONS = 1000
    SHUTDOWN_DRAIN_SECONDS = 3.0
    CAPABILITIES = AdapterCapabilities(
        text=True,
        markdown=True,
        image=True,
        buttons=True,
        mention=True,
        private_message=True,
        group_message=True,
        active_push=True,
    )

    # 命令索引。注册阶段只收集规则，run() 阶段统一排序。
    # exact_rules 处理普通命令；regex_rules 按正则固定前缀做候选过滤；
    # regex_fallback 保存没有固定前缀的正则，数量应尽量少。
    exact_rules: Dict[str, List[QqCommandRule]] = {}
    regex_rules: Dict[str, List[QqCommandRule]] = {}
    regex_fallback: List[QqCommandRule] = []
    regex_prefix_lengths: Set[int] = set()
    _register_order = 0

    # webhook 必须快速 ACK，不能在 HTTP 请求协程里跑业务。
    # 这里使用固定 worker + 有界队列，避免高峰时无限创建 task 或堆内存。
    _event_queue: asyncio.Queue[QqMessageEvent] | None = None
    _event_worker_tasks: Set[asyncio.Task] = set()
    _waiting_events = 0
    _waiting_guard = asyncio.Lock()

    # QQ 按钮点击需要主动 ACK，否则客户端会显示“第三方请求失败”一类提示。
    # ACK 也走固定 worker，避免大量按钮点击时创建临时协程。
    _interaction_ack_queue: asyncio.Queue[str] | None = None
    _interaction_ack_worker_tasks: Set[asyncio.Task] = set()
    _interaction_ack_executor: ThreadPoolExecutor | None = None

    # 同一个入口身份按顺序处理，避免连续命令的状态与回复次序交叉。
    # USER_MAX_WAITING_EVENTS 防止单人刷屏占满全局队列。
    _user_event_locks: Dict[str, asyncio.Lock] = {}
    _user_event_counts: Dict[str, int] = {}
    _user_event_guard = asyncio.Lock()

    # QQ 有可能把同一条普通消息按不同事件类型投递，也可能重试投递
    # 同一事件。这里做短时间去重，并用硬上限防止异常流量下 seen 缓存
    # 无限增长。
    _seen_event_ids: Dict[str, float] = {}
    _seen_event_order: deque[Tuple[float, str]] = deque()
    _seen_event_guard = asyncio.Lock()

    @staticmethod
    async def run() -> None:
        """启动 QQ webhook 驱动器。

        这里不创建网络连接；QQ webhook 的入口由 FastAPI router 提供。
        run() 只做配置提醒和命令索引整理，保持适配器生命周期一致。
        """

        if not client.app_id:
            logger.opt(colors=True).warning(f"{C.warn('QQ bot app_id 未配置')}")
        if not client.client_secret:
            logger.opt(colors=True).warning(
                f"{C.warn('QQ bot secret 未配置，开放平台回调验证会失败')}"
            )
        else:
            logger.opt(colors=True).success(f"{C.ok('QQ bot 已启用')}")
        QqEventHandler._build_command_index()
        await manager.start()
        await QqEventHandler._start_queues()
        logger.opt(colors=True).success(
            C.join(
                C.ok("QQ webhook 已就绪"),
                C.kv(
                    "path",
                    (config.get("QQ_EVENT_PATH", "/qq/events") or "/qq/events").rstrip("/"),
                ),
                C.kv("exact", len(QqEventHandler.exact_rules)),
                C.kv("regex", QqEventHandler._regex_rule_count()),
                C.kv("workers", QqEventHandler.EVENT_WORKERS),
            )
        )

    @staticmethod
    async def shutdown() -> None:
        """停止 QQ 后台事件任务，并清理事件去重缓存。"""

        await QqEventHandler._shutdown_queues()
        await manager.shutdown()

        async with QqEventHandler._seen_event_guard:
            QqEventHandler._seen_event_ids.clear()
            QqEventHandler._seen_event_order.clear()
        async with QqEventHandler._user_event_guard:
            QqEventHandler._user_event_locks.clear()
            QqEventHandler._user_event_counts.clear()

    @staticmethod
    async def _start_queues() -> None:
        """启动固定数量的事件 worker 和按钮 ACK worker。

        run() 在 FastAPI lifespan 中调用，理论上只会执行一次；这里仍做幂等
        判断，避免测试或热重载场景重复启动 worker。
        """

        if not QqEventHandler._event_worker_tasks:
            QqEventHandler._event_queue = asyncio.Queue(maxsize=QqEventHandler.MAX_WAITING_EVENTS)
            for index in range(QqEventHandler.EVENT_WORKERS):
                task = asyncio.create_task(
                    QqEventHandler._event_worker(index),
                    name=f"qq-event-worker-{index}",
                )
                QqEventHandler._event_worker_tasks.add(task)
                task.add_done_callback(QqEventHandler._event_worker_tasks.discard)

        if not QqEventHandler._interaction_ack_worker_tasks:
            QqEventHandler._interaction_ack_executor = ThreadPoolExecutor(
                max_workers=QqEventHandler.INTERACTION_ACK_WORKERS,
                thread_name_prefix="qq-ack",
            )
            QqEventHandler._interaction_ack_queue = asyncio.Queue(
                maxsize=QqEventHandler.MAX_WAITING_INTERACTIONS,
            )
            for index in range(QqEventHandler.INTERACTION_ACK_WORKERS):
                task = asyncio.create_task(
                    QqEventHandler._interaction_ack_worker(index),
                    name=f"qq-interaction-ack-worker-{index}",
                )
                QqEventHandler._interaction_ack_worker_tasks.add(task)
                task.add_done_callback(QqEventHandler._interaction_ack_worker_tasks.discard)

    @staticmethod
    async def _shutdown_queues() -> None:
        """等待队列短暂清空，然后取消固定 worker。

        顺序很重要：先 drain，再 cancel。否则 worker 被取消后队列永远不会
        task_done，queue.join() 会卡住。
        """

        await QqEventHandler._drain_event_queue()
        await QqEventHandler._drain_interaction_ack_queue()
        await QqEventHandler._cancel_worker_tasks(QqEventHandler._event_worker_tasks)
        await QqEventHandler._cancel_worker_tasks(QqEventHandler._interaction_ack_worker_tasks)
        QqEventHandler._event_queue = None
        QqEventHandler._interaction_ack_queue = None
        QqEventHandler._shutdown_interaction_ack_executor()

    @staticmethod
    def _shutdown_interaction_ack_executor() -> None:
        """关闭按钮 ACK 专用线程池，避免默认线程池残留 OpenAPI 任务。"""

        executor = QqEventHandler._interaction_ack_executor
        QqEventHandler._interaction_ack_executor = None
        if executor is None:
            return
        executor.shutdown(wait=True, cancel_futures=True)

    @staticmethod
    async def _drain_event_queue() -> None:
        """关闭前尽量处理完已接收的消息事件。"""

        queue = QqEventHandler._event_queue
        if queue is None:
            return

        try:
            await asyncio.wait_for(queue.join(), timeout=QqEventHandler.SHUTDOWN_DRAIN_SECONDS)
        except asyncio.TimeoutError:
            dropped = await QqEventHandler._drop_waiting_events(queue)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 事件队列关闭等待超时"),
                    C.kv("dropped", dropped),
                    C.kv("waiting", queue.qsize()),
                )
            )

    @staticmethod
    async def _drain_interaction_ack_queue() -> None:
        """关闭前尽量确认已经收到的按钮回调。"""

        queue = QqEventHandler._interaction_ack_queue
        if queue is None:
            return

        try:
            await asyncio.wait_for(queue.join(), timeout=QqEventHandler.SHUTDOWN_DRAIN_SECONDS)
        except asyncio.TimeoutError:
            dropped = QqEventHandler._drop_waiting_interactions(queue)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 按钮 ACK 队列关闭等待超时"),
                    C.kv("dropped", dropped),
                    C.kv("waiting", queue.qsize()),
                )
            )

    @staticmethod
    async def _drop_waiting_events(queue: asyncio.Queue[QqMessageEvent]) -> int:
        """丢弃还没被 worker 取走的事件，并释放排队名额。"""

        dropped = 0
        while True:
            try:
                event = queue.get_nowait()
            except asyncio.QueueEmpty:
                return dropped

            await QqEventHandler._release_waiting_event()
            await QqEventHandler._release_user_event(event.client_id)
            queue.task_done()
            dropped += 1

    @staticmethod
    def _drop_waiting_interactions(queue: asyncio.Queue[str]) -> int:
        """丢弃还没被 worker 取走的按钮 ACK。"""

        dropped = 0
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return dropped

            queue.task_done()
            dropped += 1

    @staticmethod
    async def _cancel_worker_tasks(tasks: Set[asyncio.Task]) -> None:
        """取消并回收一组固定 worker。"""

        running = list(tasks)
        for task in running:
            task.cancel()

        if running:
            await asyncio.gather(*running, return_exceptions=True)
        tasks.clear()

    @staticmethod
    async def dispatch(*args, **kwargs) -> dict:
        """BaseAdapter 入口：处理一份 QQ webhook payload。

        launch 生命周期只要求适配器暴露 dispatch；QQ 实际语义是
        handle_webhook，所以这里只做很薄的一层转发。
        """

        payload = kwargs.get("payload")
        if payload is None and args:
            payload = args[0]
        return await QqEventHandler.handle_webhook(payload)

    @staticmethod
    async def handle_webhook(payload: Any) -> dict:
        """接收 QQ webhook payload，快速 ACK 后把业务处理放进后台。

        非消息事件也必须 ACK，否则开放平台可能认为回调失败。
        能解析成消息事件的 payload 会进入后台队列继续匹配业务命令。
        """

        if not isinstance(payload, dict):
            return ACK_RESPONSE

        event = parse_message_event(payload)
        if event is not None:
            logger.opt(colors=True).debug(
                C.join(
                    C.ok("QQ webhook 已接收"),
                    *QqEventHandler._event_log_parts(event, include_message=False),
                )
            )
            QqEventHandler._ack_interaction(event)
            await QqEventHandler._enqueue_event(event)
        else:
            event_type = str(payload.get("t") or "").strip()
            is_unparsed_interaction = event_type == "INTERACTION_CREATE"
            log = logger.opt(colors=True)
            write = log.warning if is_unparsed_interaction else log.debug
            write(
                C.join(
                    C.warn("QQ 按钮事件无法解析") if is_unparsed_interaction else C.ok("QQ webhook 已确认"),
                    *QqEventHandler._payload_log_parts(payload),
                )
            )

        return ACK_RESPONSE

    @staticmethod
    def handler(
        cmd: Union[Command, List[Command]],
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册 QQ 命令处理函数。

        业务包通过 MessageHandler 统一注册命令时，会间接调用到这里。
        QQ 驱动器只关心命令匹配规则，不要求业务知道 QQ webhook 细节。
        """

        def wrapper(func: Callable) -> Callable:
            for item in QqEventHandler._normalize_commands(cmd):
                if isinstance(item, str):
                    QqEventHandler._register_exact_command(item, func, priority, block, metadata)
                elif isinstance(item, re.Pattern):
                    QqEventHandler._register_regex_command(item, func, priority, block, metadata)
                else:
                    raise TypeError("cmd 只支持 str、re.Pattern，或它们组成的 list/tuple/set")
            return func

        return wrapper

    @staticmethod
    async def validation(payload: dict) -> dict:
        """处理 QQ 开放平台回调地址验证。

        开放平台配置回调地址时会发送 op=13。这个流程只返回签名，
        不进入命令队列，也不需要设置当前 QQ 事件上下文。
        """

        data = payload.get("d")
        if not isinstance(data, dict):
            raise ValueError("QQ 回调验证缺少 d")

        plain_token = str(data.get("plain_token") or "").strip()
        event_ts = str(data.get("event_ts") or "").strip()
        if not plain_token or not event_ts:
            raise ValueError("QQ 回调验证缺少 plain_token 或 event_ts")

        bot_secret = config.get("QQ_BOT_SECRET", "").strip()
        signature = make_validation_signature(bot_secret, plain_token, event_ts)
        return {
            "plain_token": plain_token,
            "signature": signature,
        }

    @staticmethod
    async def _enqueue_event(event: QqMessageEvent) -> None:
        """把已解析的 QQ 消息事件放入后台任务队列。

        先占排队名额，再声明事件去重，最后执行非阻塞入队。去重声明只在
        成功入队后保留；任一失败分支都会释放名额并撤销声明，让 QQ 重试
        仍有机会处理该事件。
        """

        queue = QqEventHandler._event_queue
        if queue is None:
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 事件队列未启动"),
                    *QqEventHandler._event_log_parts(event, include_message=False),
                )
            )
            return

        if not await QqEventHandler._reserve_user_event(event.client_id):
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 单用户事件排队已满"),
                    *QqEventHandler._event_log_parts(event, include_message=False),
                    C.kv("max_waiting", QqEventHandler.USER_MAX_WAITING_EVENTS),
                )
            )
            return

        if not await QqEventHandler._reserve_waiting_event():
            await QqEventHandler._release_user_event(event.client_id)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ webhook 后台队列已满"),
                    C.kv("max_waiting", QqEventHandler.MAX_WAITING_EVENTS),
                )
            )
            return

        if not await QqEventHandler._remember_event_once(event):
            await QqEventHandler._release_waiting_event()
            await QqEventHandler._release_user_event(event.client_id)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 重复事件已跳过"),
                    *QqEventHandler._event_log_parts(event, include_message=False),
                )
            )
            return

        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            await QqEventHandler._forget_event(event)
            await QqEventHandler._release_waiting_event()
            await QqEventHandler._release_user_event(event.client_id)
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ webhook 后台队列已满"),
                    C.kv("max_waiting", QqEventHandler.MAX_WAITING_EVENTS),
                )
            )
            return

        emit_message_event(
            event_from_incoming(
                adapter="qq",
                client_id=event.client_id,
                request_id=event.event_id or event.message_id,
                message_type="text",
                content=event.content,
                sender_name=event.sender_name,
            )
        )

    @staticmethod
    def _ack_interaction(event: QqMessageEvent) -> None:
        """把按钮回调确认请求放入 ACK 队列。

        这个函数不能 await 网络请求；它运行在 webhook ACK 热路径上，只做
        非阻塞入队。队列满时宁可丢弃 ACK，也不能拖慢开放平台回调。
        """

        if not event.interaction_id:
            return

        queue = QqEventHandler._interaction_ack_queue
        if queue is None:
            return

        try:
            queue.put_nowait(event.interaction_id)
        except asyncio.QueueFull:
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 按钮 ACK 队列已满"),
                    C.kv("interaction", QqEventHandler._short_id(event.interaction_id)),
                    C.kv("max_waiting", QqEventHandler.MAX_WAITING_INTERACTIONS),
                )
            )

    @staticmethod
    async def _event_worker(index: int) -> None:
        """固定事件 worker：从队列取消息并执行命令处理。"""

        queue = QqEventHandler._event_queue
        if queue is None:
            return

        try:
            while True:
                event = await queue.get()
                try:
                    await QqEventHandler._run_event_task(event)
                except Exception as exc:
                    logger.opt(colors=True, exception=exc).error(
                        C.join(
                            C.fail("QQ 事件 worker 异常"),
                            C.kv("worker", index),
                            *QqEventHandler._event_log_parts(event, include_message=False),
                        )
                    )
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            return

    @staticmethod
    async def _interaction_ack_worker(index: int) -> None:
        """固定按钮 ACK worker：确认按钮回调，避免临时任务暴涨。"""

        queue = QqEventHandler._interaction_ack_queue
        if queue is None:
            return

        try:
            while True:
                interaction_id = await queue.get()
                try:
                    await QqEventHandler._ack_interaction_direct(interaction_id)
                except Exception as exc:
                    logger.opt(colors=True, exception=exc).warning(
                        C.join(
                            C.warn("QQ 按钮 ACK worker 异常"),
                            C.kv("worker", index),
                            C.kv("interaction", QqEventHandler._short_id(interaction_id)),
                        )
                    )
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            return

    @staticmethod
    async def _ack_interaction_direct(interaction_id: str) -> None:
        """后台确认按钮回调，避免阻塞 webhook ACK。"""

        try:
            await QqEventHandler._run_ack_sync(client.ack_interaction, interaction_id)
        except Exception as exc:
            logger.opt(colors=True, exception=exc).warning(
                C.join(
                    C.warn("QQ 按钮回调确认失败"),
                    C.kv("interaction", QqEventHandler._short_id(interaction_id)),
                )
            )

    @staticmethod
    async def _run_ack_sync(func, *args):
        """在按钮 ACK 专用线程池里运行同步 OpenAPI 调用。

        正常生命周期里 run() 会先创建线程池，再启动 ACK worker。这里不再
        退回 asyncio 默认线程池，避免驱动器未启动时悄悄产生不可控后台线程。
        """

        executor = QqEventHandler._interaction_ack_executor
        if executor is None:
            raise RuntimeError("QQ 按钮 ACK 线程池未启动")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    @staticmethod
    async def _run_event_task(event: QqMessageEvent) -> None:
        """在单用户顺序限制和超时限制下处理事件。

        固定 worker 控制了全局并发数；这里的 user_lock 只负责同一个
        client_id 的顺序一致性。
        """

        async def run_with_limits() -> bool:
            user_lock = await QqEventHandler._user_lock(event.client_id)
            async with user_lock:
                return await QqEventHandler._process_message_event(event)

        try:
            await asyncio.wait_for(run_with_limits(), timeout=QqEventHandler.EVENT_TASK_TIMEOUT)
        except asyncio.TimeoutError:
            logger.opt(colors=True).warning(
                C.join(
                    C.warn("QQ 事件处理超时，已终止"),
                    *QqEventHandler._event_log_parts(event, include_message=False),
                    C.kv("timeout", QqEventHandler.EVENT_TASK_TIMEOUT),
                )
            )
        finally:
            await QqEventHandler._release_waiting_event()
            await QqEventHandler._release_user_event(event.client_id)

    @staticmethod
    async def _process_message_event(event: QqMessageEvent) -> bool:
        """处理单条 QQ 消息事件，并在上下文中暴露给回复器使用。"""

        event_token = current_event.set(event)
        try:
            matched = await QqEventHandler._match_event(event)
            if not matched:
                logger.opt(colors=True).debug(
                    C.join(
                        C.warn("QQ 消息未命中命令"),
                        *QqEventHandler._event_log_parts(event),
                    )
                )
                return False

            logger.opt(colors=True).success(
                C.join(
                    C.ok("QQ 命令命中"),
                    *QqEventHandler._event_log_parts(event),
                    C.kv("cmd", QqEventHandler._matched_commands_text(matched)),
                    C.kv("handlers", len(matched)),
                )
            )

            if await QqEventHandler._guard_blocked(matched[0], event):
                return True

            block_priority = None
            for item in matched:
                rule = item.rule
                if block_priority is not None and rule.priority < block_priority:
                    break

                await QqEventHandler._call_rule(item, event)

                if rule.block:
                    block_priority = rule.priority

            return True
        finally:
            current_event.reset(event_token)

    @staticmethod
    async def _guard_blocked(item: QqCommandMatch, event: QqMessageEvent) -> bool:
        """命中业务回调前执行一次命令守卫。"""

        message_context = QqEventHandler._message_context(item, event)
        context_token = set_current_message_context(message_context)
        try:
            decision = await run_command_guards(
                CommandGuardContext(
                    message_context=message_context,
                    command_metadata=item.rule.metadata,
                )
            )
            if not decision.blocked:
                return False

            if decision.reply is not None:
                await manager.send(decision.reply, event.client_id)
            return True
        finally:
            reset_current_message_context(context_token)

    @staticmethod
    async def _match_event(event: QqMessageEvent) -> List[QqCommandMatch]:
        """按 QQ 消息正文匹配已注册命令。"""

        command_text = event.content.lstrip()
        if not command_text:
            return []

        command, message = QqEventHandler._split_command(command_text)
        matched: List[QqCommandMatch] = [
            QqCommandMatch(rule=rule, command=command, message=message)
            for rule in QqEventHandler.exact_rules.get(command, [])
        ]

        for rule, match in await QqEventHandler._match_regex_command(command):
            matched.append(
                QqCommandMatch(
                    rule=rule,
                    command=command,
                    message=QqEventHandler._message_after_match(command_text, message, match),
                    match=match,
                )
            )

        matched.sort(key=lambda item: (-item.rule.priority, item.rule.order))
        return matched

    @staticmethod
    async def _call_rule(item: QqCommandMatch, event: QqMessageEvent) -> None:
        """把 QQ 事件上下文转换成业务函数可接收的参数。"""

        message_context = QqEventHandler._message_context(item, event)
        context_token = set_current_message_context(message_context)
        try:
            await call_with_dependencies(
                item.rule.func,
                {
                    "client_id": event.client_id,
                    "message": item.message,
                    "manager": manager,
                    "cmd": item.command,
                    "raw_message": event.content,
                    "message_context": message_context,
                    "sender_name": message_context.sender_name,
                    "reply_target": message_context.reply_target,
                    "adapter_capabilities": message_context.capabilities,
                    "match": item.match,
                },
            )
        finally:
            reset_current_message_context(context_token)

    @staticmethod
    def _message_context(item: QqCommandMatch, event: QqMessageEvent) -> MessageContext:
        """生成 QQ-first 的显式消息上下文。"""

        conversation_type = CONVERSATION_GROUP if event.is_group else CONVERSATION_PRIVATE
        reply_target = ReplyTarget(
            adapter="qq",
            client_id=event.client_id,
            conversation_type=conversation_type,
            driver_target=event,
        )
        return MessageContext(
            adapter="qq",
            client_id=event.client_id,
            command=item.command,
            message=item.message,
            raw_message=event.content,
            conversation_type=conversation_type,
            reply_target=reply_target,
            capabilities=QqEventHandler.CAPABILITIES,
            identity=qq_message_identity(
                event,
                bot_app_id=config.get("QQ_BOT_APP_ID", ""),
            ),
            driver_context=event,
            sender_name=event.sender_name,
        )

    @staticmethod
    async def _reserve_waiting_event() -> bool:
        """尝试占用一个全局后台事件排队名额。"""

        async with QqEventHandler._waiting_guard:
            if QqEventHandler._waiting_events >= QqEventHandler.MAX_WAITING_EVENTS:
                return False
            QqEventHandler._waiting_events += 1
            return True

    @staticmethod
    async def _release_waiting_event() -> None:
        """释放一个全局后台事件排队名额。"""

        async with QqEventHandler._waiting_guard:
            if QqEventHandler._waiting_events > 0:
                QqEventHandler._waiting_events -= 1

    @staticmethod
    async def _reserve_user_event(client_id: str) -> bool:
        """尝试占用当前用户的排队名额。"""

        async with QqEventHandler._user_event_guard:
            count = QqEventHandler._user_event_counts.get(client_id, 0)
            if count >= QqEventHandler.USER_MAX_WAITING_EVENTS:
                return False

            QqEventHandler._user_event_counts[client_id] = count + 1
            QqEventHandler._user_event_locks.setdefault(client_id, asyncio.Lock())
            return True

    @staticmethod
    async def _release_user_event(client_id: str) -> None:
        """释放当前用户的排队名额。"""

        async with QqEventHandler._user_event_guard:
            count = QqEventHandler._user_event_counts.get(client_id, 0) - 1
            if count > 0:
                QqEventHandler._user_event_counts[client_id] = count
                return

            QqEventHandler._user_event_counts.pop(client_id, None)
            QqEventHandler._user_event_locks.pop(client_id, None)

    @staticmethod
    async def _user_lock(client_id: str) -> asyncio.Lock:
        """获取当前用户的顺序处理锁。"""

        async with QqEventHandler._user_event_guard:
            return QqEventHandler._user_event_locks.setdefault(client_id, asyncio.Lock())

    @staticmethod
    async def _remember_event_once(event: QqMessageEvent) -> bool:
        """声明 QQ 事件 ID；入队失败时必须调用 _forget_event 撤销。"""

        event_key = QqEventHandler._event_dedupe_key(event)
        if not event_key:
            return True

        now_value = monotonic()
        async with QqEventHandler._seen_event_guard:
            QqEventHandler._clear_expired_event_ids(now_value)
            if event_key in QqEventHandler._seen_event_ids:
                return False

            QqEventHandler._seen_event_ids[event_key] = now_value
            QqEventHandler._seen_event_order.append((now_value, event_key))
            QqEventHandler._trim_seen_event_ids()
            return True

    @staticmethod
    async def _forget_event(event: QqMessageEvent) -> None:
        """撤销尚未成功入队的事件声明。"""

        event_key = QqEventHandler._event_dedupe_key(event)
        if not event_key:
            return
        async with QqEventHandler._seen_event_guard:
            QqEventHandler._seen_event_ids.pop(event_key, None)

    @staticmethod
    def _event_dedupe_key(event: QqMessageEvent) -> str:
        """生成 QQ 事件去重键。

        普通消息优先按 message_id 去重，兜住同一群 at 消息被 QQ 同时推成
        GROUP_AT_MESSAGE_CREATE / GROUP_MESSAGE_CREATE 的情况；按钮交互则按
        interaction_id/event_id 去重，避免同一条按钮消息上的不同点击被误杀。
        """

        if event.interaction_id:
            raw_key = event.interaction_id or event.event_id
            key_type = "interaction"
        else:
            raw_key = event.message_id or event.event_id
            key_type = "message"
        return f"{key_type}:{raw_key}" if raw_key else ""

    @staticmethod
    def _clear_expired_event_ids(now_value: float) -> None:
        """清理过期的事件去重记录。"""

        expires_before = now_value - QqEventHandler.EVENT_ID_TTL_SECONDS
        while (
            QqEventHandler._seen_event_order
            and QqEventHandler._seen_event_order[0][0] <= expires_before
        ):
            created_at, event_key = QqEventHandler._seen_event_order.popleft()
            if QqEventHandler._seen_event_ids.get(event_key) == created_at:
                QqEventHandler._seen_event_ids.pop(event_key, None)

    @staticmethod
    def _trim_seen_event_ids() -> None:
        """限制事件去重缓存上限，避免异常流量下长期占用内存。"""

        while len(QqEventHandler._seen_event_order) > QqEventHandler.MAX_SEEN_EVENT_IDS:
            created_at, event_key = QqEventHandler._seen_event_order.popleft()
            if QqEventHandler._seen_event_ids.get(event_key) == created_at:
                QqEventHandler._seen_event_ids.pop(event_key, None)

    @staticmethod
    def _build_command_index() -> None:
        """整理命令索引和排序，供后续事件快速匹配。"""

        QqEventHandler.regex_prefix_lengths = {
            len(prefix)
            for prefix in QqEventHandler.regex_rules
        }

        for rules in QqEventHandler.exact_rules.values():
            rules.sort(key=lambda rule: (-rule.priority, rule.order))
        for rules in QqEventHandler.regex_rules.values():
            rules.sort(key=lambda rule: (-rule.priority, rule.order))
        QqEventHandler.regex_fallback.sort(key=lambda rule: (-rule.priority, rule.order))

    @staticmethod
    def _regex_rule_count() -> int:
        """返回已注册正则命令数量，只用于启动日志。"""

        return sum(len(rules) for rules in QqEventHandler.regex_rules.values()) + len(
            QqEventHandler.regex_fallback
        )

    @staticmethod
    def _split_command(raw_message: str) -> Tuple[str, str]:
        """按第一个空格拆出命令片段和业务参数文本。"""

        command, separator, message = raw_message.partition(" ")
        if not separator:
            return raw_message, ""
        return command, message.strip()

    @staticmethod
    def _message_after_match(
        clean_message: str,
        split_message: str,
        match: Optional[re.Match],
    ) -> str:
        """计算正则命令命中片段之后留给业务的文本。"""

        if match is None:
            return split_message
        return clean_message[match.end() :].lstrip()

    @staticmethod
    def _payload_log_parts(payload: dict) -> List[str]:
        """把非消息 webhook 整理成简短日志片段，避免输出原始大包。"""

        data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
        return [
            C.kv("op", payload.get("op") or "-"),
            C.kv("type", payload.get("t") or "-"),
            C.kv("event", QqEventHandler._short_id(payload.get("id"))),
            C.kv("msg", QqEventHandler._short_id(data.get("id"))),
        ]

    @staticmethod
    def _event_log_parts(event: QqMessageEvent, include_message: bool = True) -> List[str]:
        """把 QQ 消息事件整理成一行摘要日志。"""

        parts = [
            C.kv("type", QqEventHandler._event_type_label(event.event_type)),
            C.kv("client", QqEventHandler._short_id(event.client_id)),
            C.kv("group", QqEventHandler._short_id(event.group_openid)),
            C.kv("msg", QqEventHandler._short_id(event.message_id)),
            C.kv("actor_source", QqEventHandler._actor_identity_source(event)),
        ]
        if event.interaction_id:
            parts.append(C.kv("interaction", QqEventHandler._short_id(event.interaction_id)))
        if include_message:
            parts.append(C.kv("message", QqEventHandler._short_text(event.content)))
        return parts

    @staticmethod
    def _actor_identity_source(event: QqMessageEvent) -> str:
        """标记 actor_openid 最终来自 user、member 还是兼容字段。"""

        if event.member_openid and event.actor_openid == event.member_openid:
            return "member"
        if event.user_openid and event.actor_openid == event.user_openid:
            return "user"
        return "fallback"

    @staticmethod
    def _event_type_label(event_type: str) -> str:
        """把开放平台事件名转换成更适合扫日志的中文标签。"""

        return {
            "C2C_MESSAGE_CREATE": "私聊",
            "GROUP_AT_MESSAGE_CREATE": "群艾特",
            "GROUP_MESSAGE_AT_CREATE": "群艾特",
            "GROUP_MESSAGE_CREATE": "群聊",
            "INTERACTION_CREATE": "按钮",
        }.get(event_type, event_type or "-")

    @staticmethod
    def _matched_commands_text(items: List[QqCommandMatch]) -> str:
        """生成命中的命令摘要，多处理函数时只展示去重后的命令。"""

        commands = []
        seen = set()
        for item in items:
            command = item.command or "-"
            if command in seen:
                continue
            seen.add(command)
            commands.append(command)

        if not commands:
            return "-"
        text = "、".join(commands[:3])
        if len(commands) > 3:
            text = f"{text} 等{len(commands)}个"
        return QqEventHandler._short_text(text, limit=60)

    @staticmethod
    def _short_id(value: object, head: int = 8, tail: int = 6) -> str:
        """缩短开放平台长 ID，日志里保留首尾方便对照。"""

        text = str(value or "").strip()
        if not text:
            return "-"
        if len(text) <= head + tail + 3:
            return text
        return f"{text[:head]}...{text[-tail:]}"

    @staticmethod
    def _short_text(value: object, limit: int = 80) -> str:
        """压缩日志正文长度，避免一条消息撑满整屏。"""

        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return "-"
        if len(text) <= limit:
            return text
        return f"{text[:limit - 1]}…"

    @staticmethod
    def _register_exact_command(
        cmd: str,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册精确命令。"""

        rule = QqEventHandler._make_rule(func=func, priority=priority, block=block, metadata=metadata)
        QqEventHandler.exact_rules.setdefault(cmd, []).append(rule)

    @staticmethod
    def _register_regex_command(
        pattern: Pattern,
        func: Callable,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册正则命令，并尝试按固定前缀建立候选索引。"""

        prefix = QqEventHandler._extract_literal_prefix(pattern.pattern)
        rule = QqEventHandler._make_rule(
            func=func,
            priority=priority,
            block=block,
            pattern=pattern,
            metadata=metadata,
        )
        if prefix:
            QqEventHandler.regex_rules.setdefault(prefix.casefold(), []).append(rule)
        else:
            QqEventHandler.regex_fallback.append(rule)

    @staticmethod
    def _make_rule(
        func: Callable,
        priority: int,
        block: bool,
        pattern: Optional[Pattern] = None,
        metadata: dict[str, Any] | None = None,
    ) -> QqCommandRule:
        """创建命令规则，并记录注册顺序用于稳定排序。"""

        order = QqEventHandler._register_order
        QqEventHandler._register_order += 1
        return QqCommandRule(
            func=func,
            priority=priority,
            block=block,
            order=order,
            pattern=pattern,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    async def _match_regex_command(cmd: str) -> List[Tuple[QqCommandRule, re.Match]]:
        """匹配正则命令。"""

        matched = []
        key = cmd.casefold()
        seen_rules: Set[int] = set()

        for length in QqEventHandler.regex_prefix_lengths:
            if length > len(key):
                continue

            for start in range(0, len(key) - length + 1):
                for rule in QqEventHandler.regex_rules.get(key[start : start + length], []):
                    rule_id = id(rule)
                    if rule_id in seen_rules:
                        continue

                    seen_rules.add(rule_id)
                    match = rule.pattern.search(cmd)
                    if match:
                        matched.append((rule, match))

        for rule in QqEventHandler.regex_fallback:
            rule_id = id(rule)
            if rule_id in seen_rules:
                continue

            seen_rules.add(rule_id)
            match = rule.pattern.search(cmd)
            if match:
                matched.append((rule, match))

        return matched

    @staticmethod
    def _extract_literal_prefix(source: str) -> str:
        """从正则源码中提取可用于候选过滤的固定文本前缀。"""

        index = 1 if source.startswith("^") else 0
        prefix = []
        metacharacters = set(".^$*+?{}[]|()")

        while index < len(source):
            char = source[index]

            if char in metacharacters:
                break

            if char == "\\":
                if index + 1 >= len(source):
                    break

                next_char = source[index + 1]
                if next_char in "AbBdDsSwWZ0123456789":
                    break

                prefix.append(next_char)
                index += 2
                continue

            prefix.append(char)
            index += 1

        return "".join(prefix)

    @staticmethod
    def _normalize_commands(value: Any) -> list:
        """把单个命令或命令集合统一成 list。"""

        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]


__all__ = ["QqEventHandler", "manager"]
