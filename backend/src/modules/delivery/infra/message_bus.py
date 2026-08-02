"""消息总线：实现入站队列、出站队列和发布/订阅机制。

MessageBus 是解耦渠道与核心逻辑的关键组件：
- InboundQueue: 渠道适配器发布消息到此队列
- OutboundPort: AgentLoop 投递回复的抽象接口
- BusOutboundPort: 将 OutboundDispatch 转换为 OutboundMessage 并发布到出站队列
- OutboundQueue: 后台 dispatch_outbound 任务持续监听出站队列，分发到渠道适配器
"""

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from uuid import uuid4

from modules.delivery.domain.messages import ChannelDeliveryResult, OutboundMessage
from modules.delivery.infra.outbox import SQLiteOutboxStore

logger = logging.getLogger(__name__)


@dataclass
class InboundQueue:
    """入站消息队列：线程安全的 FIFO 队列。"""

    _queue: deque[Any] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def publish(self, message: Any) -> None:
        """向入站队列发布一条消息。"""
        with self._lock:
            self._queue.append(message)
            logger.debug("inbound published: channel=%s session=%s", message.channel, message.session_id)

    def consume_one(self) -> Any | None:
        """从入站队列消费一条消息（非阻塞）。"""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    async def consume_one_async(self, poll_interval_ms: int = 100) -> Any | None:
        """从入站队列阻塞消费一条消息（异步，适用于 AgentLoop 主循环）。"""
        while True:
            with self._lock:
                if self._queue:
                    return self._queue.popleft()
            await asyncio.sleep(poll_interval_ms / 1000.0)

    def consume_all(self) -> list[Any]:
        """消费入站队列中的所有消息。"""
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._queue)


@dataclass
class OutboundDispatch:
    """出站投递指令：AgentLoop 在 AfterTurn 阶段创建的投递消息。

    由 BusOutboundPort 转换为 OutboundMessage 并投递到出站队列。
    """
    channel: str
    session_id: str
    text: str
    chat_id: str = ""
    delivery_id: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class DeliveryReceipt:
    """渠道投递完成后的稳定回执。"""

    delivery_id: str
    delivered: bool
    attempts: int = 0
    error: str = ""
    uncertain: bool = False
    retryable: bool = True


class DeliveryHandle:
    """允许不同事件循环和线程等待同一投递结果。"""

    def __init__(self, delivery_id: str) -> None:
        self.delivery_id = delivery_id
        self._event = threading.Event()
        self._receipt: DeliveryReceipt | None = None

    def complete(self, receipt: DeliveryReceipt) -> None:
        if self._event.is_set():
            return
        self._receipt = receipt
        self._event.set()

    def wait(self, timeout: float | None = None) -> DeliveryReceipt:
        if not self._event.wait(timeout):
            return DeliveryReceipt(
                delivery_id=self.delivery_id,
                delivered=False,
                error="delivery timeout",
            )
        if self._receipt is None:
            return DeliveryReceipt(
                delivery_id=self.delivery_id,
                delivered=False,
                error="delivery receipt missing",
            )
        return self._receipt

    def receipt(self) -> DeliveryReceipt | None:
        """非阻塞读取当前回执。"""

        return self._receipt if self._event.is_set() else None


@dataclass
class OutboundQueue:
    """出站消息队列：支持订阅者模式的出站队列。

    按 channel 分类存储订阅者回调，确保回复只发给对应渠道。
    """

    _queue: deque[OutboundMessage] = field(default_factory=deque)
    _subscribers: dict[str, list[Callable[[OutboundMessage], None]]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def subscribe(self, channel: str, callback: Callable[[OutboundMessage], None]) -> None:
        """注册出站消息订阅者（渠道适配器的回调函数）。

        按 channel 分类存储订阅者，确保回复只发给对应渠道。
        """
        with self._lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = []
            if callback not in self._subscribers[channel]:
                self._subscribers[channel].append(callback)
                logger.debug("outbound subscriber registered: channel=%s", channel)

    def unsubscribe(self, channel: str, callback: Callable[[OutboundMessage], None]) -> None:
        """取消订阅。"""
        with self._lock:
            if channel in self._subscribers and callback in self._subscribers[channel]:
                self._subscribers[channel].remove(callback)
                if not self._subscribers[channel]:
                    del self._subscribers[channel]

    def publish(self, message: OutboundMessage) -> None:
        """投递一条出站消息到队列（由 BusOutboundPort 调用）。"""
        with self._lock:
            self._queue.append(message)
            logger.debug(f"outbound queued: channel={message.channel} session={message.session_id} queue_size={len(self._queue)}")

    def dispatch(self, message: OutboundMessage) -> None:
        """同步投递一条出站消息：入队并立即推送给对应渠道的所有订阅者。"""
        with self._lock:
            self._queue.append(message)
            subs = list(self._subscribers.get(message.channel, []))
        for callback in subs:
            try:
                callback(message)
            except Exception:
                logger.exception("outbound subscriber callback failed for channel=%s", message.channel)

    async def dispatch_async(self, message: OutboundMessage) -> None:
        """异步投递一条出站消息，支持协程回调。"""
        with self._lock:
            self._queue.append(message)
            subs = list(self._subscribers.get(message.channel, []))
        for callback in subs:
            try:
                result = callback(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("outbound subscriber async dispatch failed for channel=%s", message.channel)

    def consume_one(self) -> OutboundMessage | None:
        """从出站队列消费一条消息（非阻塞）。"""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    async def consume_one_async(self, poll_interval_ms: int = 100) -> OutboundMessage | None:
        """从出站队列阻塞消费一条消息（异步，适用于后台 dispatch 任务）。"""
        while True:
            with self._lock:
                if self._queue:
                    msg = self._queue.popleft()
                    logger.debug(f"consumed outbound message: channel={msg.channel} session={msg.session_id} remaining={len(self._queue)}")
                    return msg
            await asyncio.sleep(poll_interval_ms / 1000.0)
        return None

    def drain(self) -> list[OutboundMessage]:
        """清空并返回到目前为止入队的消息。"""
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return sum(len(subs) for subs in self._subscribers.values())

    def has_subscribers(self, channel: str) -> bool:
        """检查指定渠道是否有注册的订阅者。"""
        with self._lock:
            return channel in self._subscribers and len(self._subscribers[channel]) > 0


class OutboundPort(Protocol):
    """出站接口：AgentLoop 在 AfterTurn 阶段通过此接口投递回复。

    实现类 BusOutboundPort 负责将 OutboundDispatch 转换为 OutboundMessage
    并投递到出站队列。
    """
    def send(self, dispatch: OutboundDispatch) -> DeliveryHandle:
        ...

    async def send_and_wait(
        self,
        dispatch: OutboundDispatch,
        timeout: float = 30.0,
    ) -> DeliveryReceipt:
        ...


@dataclass
class BusOutboundPort(OutboundPort):
    """OutboundPort 的实现：将 OutboundDispatch 发布到 OutboundQueue。

    AgentLoop/Pipeline 使用此接口投递回复，不直接操作出站队列。
    """
    _queue: OutboundQueue
    _outbox: SQLiteOutboxStore | None = None
    _handles: dict[str, DeliveryHandle] = field(default_factory=dict)
    _handles_lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, dispatch: OutboundDispatch) -> DeliveryHandle:
        """持久化消息并返回可等待的投递句柄。"""

        delivery_id = dispatch.delivery_id or uuid4().hex
        chat_id = dispatch.chat_id or _resolve_chat_id(
            dispatch.channel,
            dispatch.session_id,
            dispatch.metadata,
        )
        handle = DeliveryHandle(delivery_id)
        if self._outbox is not None:
            existing = self._outbox.get(delivery_id)
            if existing is not None and existing.status == "delivered":
                handle.complete(
                    DeliveryReceipt(
                        delivery_id=delivery_id,
                        delivered=True,
                        attempts=existing.attempts,
                    )
                )
                return handle
        with self._handles_lock:
            self._handles[delivery_id] = handle
        if self._outbox is not None:
            self._outbox.prepare(
                delivery_id=delivery_id,
                channel=dispatch.channel,
                session_id=dispatch.session_id,
                chat_id=chat_id,
                text=dispatch.text,
                metadata=dispatch.metadata,
            )
        message = OutboundMessage(
            channel=dispatch.channel,
            session_id=dispatch.session_id,
            text=dispatch.text,
            chat_id=chat_id,
            delivery_id=delivery_id,
            metadata=dispatch.metadata,
        )
        self._queue.publish(message)
        return handle

    async def send_and_wait(
        self,
        dispatch: OutboundDispatch,
        timeout: float = 30.0,
    ) -> DeliveryReceipt:
        """发送消息并异步等待渠道回执。"""

        handle = self.send(dispatch)
        deadline = time.monotonic() + max(0.01, timeout)
        while time.monotonic() < deadline:
            receipt = handle.receipt()
            if receipt is not None:
                return receipt
            await asyncio.sleep(0.05)
        return DeliveryReceipt(
            delivery_id=handle.delivery_id,
            delivered=False,
            error="delivery timeout",
        )

    def complete(self, receipt: DeliveryReceipt) -> None:
        """提交回执并唤醒等待方。"""

        with self._handles_lock:
            handle = self._handles.pop(receipt.delivery_id, None)
        if handle is not None:
            handle.complete(receipt)


@dataclass
class MessageBus:
    """消息总线：解耦渠道和核心逻辑的中心枢纽。

    提供两个方向的队列：
    - inbound: 渠道 → 核心
    - outbound: 核心 → 渠道
    - outbound_port: AgentLoop 投递回复的抽象接口

    后台任务 dispatch_outbound 持续监听出站队列，
    将消息分发给对应渠道的订阅者。
    """

    inbound: InboundQueue = field(default_factory=InboundQueue)
    outbound: OutboundQueue = field(default_factory=OutboundQueue)
    outbox_store: SQLiteOutboxStore | None = None
    outbound_port: BusOutboundPort = field(init=False)
    _dispatch_task: asyncio.Task | None = field(default=None, repr=False)
    _retry_delay_s: float = 2.0
    # 默认不恢复进程启动前的历史消息，避免停止期间积压消息在启动时集中发送。
    outbox_recovery_window_s: float = 0.0
    outbox_recovery_limit: int = 100
    # 运行期间的失败消息使用有限退避重试，避免临时网络故障导致消息永久停留在 failed。
    _runtime_retry_base_delay_s: float = 10.0
    _runtime_retry_max_delay_s: float = 300.0
    _runtime_retry_max_age_s: float = 3600.0
    _runtime_retry_tasks: set[asyncio.Task] = field(default_factory=set, repr=False)
    _runtime_retrying_ids: set[str] = field(default_factory=set, repr=False)
    _runtime_retry_counts: dict[str, int] = field(default_factory=dict, repr=False)
    _running: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self.outbound_port = BusOutboundPort(
            _queue=self.outbound,
            _outbox=self.outbox_store,
        )
        self._restore_outbox()

    def _restore_outbox(self) -> None:
        """启动时恢复尚未确认送达的消息。"""

        if self.outbox_store is None:
            return
        unknown_count = self.outbox_store.mark_interrupted_sending_unknown()
        if unknown_count:
            logger.warning(
                "检测到 %d 条结果未知的中断投递，已停止自动重放",
                unknown_count,
            )
        now = time.time()
        if self.outbox_recovery_window_s <= 0:
            expired_count = self.outbox_store.expire_before(now)
            if expired_count:
                logger.warning(
                    "启动恢复已关闭，将 %d 条历史出站消息标记为过期，不再自动补发",
                    expired_count,
                )
            return

        expired_count = self.outbox_store.expire_before(
            now - self.outbox_recovery_window_s
        )
        if expired_count:
            logger.warning(
                "已将 %d 条超出恢复窗口的出站消息标记为过期，不再自动补发",
                expired_count,
            )
        records = self.outbox_store.list_recoverable(
            limit=self.outbox_recovery_limit,
            max_age_seconds=self.outbox_recovery_window_s,
            now=now,
        )
        for record in records:
            metadata = dict(record.metadata)
            metadata.setdefault("outbox_created_at", record.created_at)
            self.outbound.publish(
                OutboundMessage(
                    channel=record.channel,
                    session_id=record.session_id,
                    text=record.text,
                    chat_id=record.chat_id,
                    delivery_id=record.delivery_id,
                    metadata=metadata,
                )
            )
        if records:
            logger.info("已恢复 %d 条未确认出站消息", len(records))

    def publish_inbound(self, message: Any) -> None:
        """渠道适配器调用：将入站消息发布到总线。"""
        self.inbound.publish(message)

    def consume_inbound(self) -> Any | None:
        """AgentLoop 调用：从总线拉取一条入站消息。"""
        return self.inbound.consume_one()

    async def consume_inbound_async(self, poll_interval_ms: int = 100) -> Any | None:
        """AgentLoop 调用：从总线异步阻塞拉取一条入站消息。"""
        return await self.inbound.consume_one_async(poll_interval_ms)

    def subscribe_outbound(self, channel: str, callback: Callable[[OutboundMessage], None]) -> None:
        """渠道适配器调用：注册出站订阅回调。

        渠道启动时调用此方法注册 on_response 回调函数。
        MessageBus 后台 dispatch_outbound 任务在收到出站消息时调用此回调。
        """
        self.outbound.subscribe(channel, callback)

    def unsubscribe_outbound(self, channel: str, callback: Callable[[OutboundMessage], None]) -> None:
        """渠道适配器调用：取消出站订阅。"""
        self.outbound.unsubscribe(channel, callback)

    def dispatch_outbound(self, message: OutboundMessage) -> None:
        """将出站消息直接投递到出站队列（兼容旧接口）。

        新代码应使用 outbound_port.send(dispatch) 和 dispatch_outbound 后台任务。
        """
        self.outbound.publish(message)

    async def start_dispatch_task(self) -> None:
        """启动后台出站分发任务。

        持续从出站队列消费消息，分发给对应渠道的订阅者。
        带容错重试机制：失败后等待 2 秒重试一次；再次失败发送降级错误通知。
        """
        if self._running:
            return
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("dispatch_outbound background task started")
        # 等待任务完成（实际上会一直运行直到 stop_dispatch_task 被调用）
        try:
            await self._dispatch_task
        except asyncio.CancelledError:
            logger.info("dispatch task cancelled")

    async def stop_dispatch_task(self) -> None:
        """停止后台出站分发任务及其运行期重试任务。"""
        self._running = False
        retry_tasks = list(self._runtime_retry_tasks)
        for task in retry_tasks:
            task.cancel()
        if retry_tasks:
            await asyncio.gather(*retry_tasks, return_exceptions=True)
        self._runtime_retry_tasks.clear()
        self._runtime_retrying_ids.clear()
        self._runtime_retry_counts.clear()
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            self._dispatch_task = None
        logger.info("dispatch_outbound background task stopped")

    async def _dispatch_loop(self) -> None:
        """后台分发循环：从出站队列消费消息并分发。

        通过 while 循环阻塞等待新消息，确保不占用主线程资源。
        每个出站消息遍历对应 channel 的所有订阅者并调用回调。
        容错重试：失败后等待 2 秒重试一次；再次失败发送降级错误通知。
        """
        logger.info("dispatch loop started, waiting for messages...")
        while self._running:
            message = await self.outbound.consume_one_async(poll_interval_ms=100)
            if message is None:
                continue

            channel = message.channel
            logger.info("dispatching outbound message: channel=%s, text=%s", channel, message.text[:100] if message.text else "EMPTY")
            
            if not self.outbound.has_subscribers(channel):
                logger.warning(
                    "outbound dispatch: no subscribers for channel=%s", channel
                )
                self._finish_delivery(
                    message,
                    delivered=False,
                    attempts=0,
                    error=f"no subscribers for channel={channel}",
                    retryable=False,
                )
                continue

            # 同一渠道只要有一个真实发送者确认成功，本条消息即视为送达。
            subscribers = self._get_subscribers(channel)
            logger.debug("found %d subscribers for channel=%s", len(subscribers), channel)
            delivered = False
            uncertain = False
            retryable = True
            last_error = ""
            total_attempts = 0
            for callback in subscribers:
                receipt = await self._dispatch_with_retry(message, callback)
                total_attempts += receipt.attempts
                if receipt.delivered:
                    delivered = True
                    last_error = ""
                    break
                if receipt.uncertain:
                    uncertain = True
                    retryable = False
                    last_error = receipt.error
                    break
                retryable = receipt.retryable
                last_error = receipt.error
                if not receipt.retryable:
                    break
            self._finish_delivery(
                message,
                delivered=delivered,
                attempts=total_attempts,
                error=last_error,
                uncertain=uncertain,
                retryable=retryable,
            )
            if not delivered and not uncertain and retryable:
                self._schedule_runtime_retry(message)

    async def _dispatch_with_retry(
        self, message: OutboundMessage, callback: Callable[[OutboundMessage], None]
    ) -> DeliveryReceipt:
        """带容错重试的出站分发。

        - 首次调用失败：等待 2 秒后重试一次
        - 仍然失败：发送降级错误通知给用户，而非静默丢弃
        """
        last_error = ""
        for attempt in range(1, 3):
            if self.outbox_store is not None:
                self.outbox_store.mark_sending(message.delivery_id)
            try:
                result = callback(message)
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, ChannelDeliveryResult):
                    if result.delivered:
                        return DeliveryReceipt(
                            delivery_id=message.delivery_id,
                            delivered=True,
                            attempts=attempt,
                        )
                    if result.uncertain or not result.retryable:
                        return DeliveryReceipt(
                            delivery_id=message.delivery_id,
                            delivered=False,
                            attempts=attempt,
                            error=result.error or "channel rejected outbound message",
                            uncertain=result.uncertain,
                            retryable=result.retryable,
                        )
                    raise RuntimeError(
                        result.error or "channel rejected outbound message"
                    )
                if result is False:
                    raise RuntimeError("channel rejected outbound message")
                return DeliveryReceipt(
                    delivery_id=message.delivery_id,
                    delivered=True,
                    attempts=attempt,
                )
            except Exception as exc:
                last_error = str(exc)
                logger.exception(
                    "outbound dispatch attempt=%d failed channel=%s",
                    attempt,
                    message.channel,
                )
                if attempt < 2:
                    await asyncio.sleep(self._retry_delay_s)
        return DeliveryReceipt(
            delivery_id=message.delivery_id,
            delivered=False,
            attempts=2,
            error=last_error or "delivery failed",
            retryable=True,
        )

    def _schedule_runtime_retry(self, message: OutboundMessage) -> None:
        """为运行期间的明确可重试失败安排一次退避重试。"""

        if self.outbox_store is None or not self._running:
            return
        delivery_id = message.delivery_id
        if delivery_id in self._runtime_retrying_ids:
            return
        record = self.outbox_store.get(delivery_id)
        if record is None or record.status != "failed":
            return
        age = max(0.0, time.time() - record.created_at)
        if age >= self._runtime_retry_max_age_s:
            self.outbox_store.mark_expired(delivery_id)
            logger.warning("出站消息已超过运行期重试时限，标记为过期: %s", delivery_id)
            return

        retry_count = self._runtime_retry_counts.get(delivery_id, 0)
        delay = min(
            self._runtime_retry_base_delay_s * (2 ** retry_count),
            self._runtime_retry_max_delay_s,
        )
        self._runtime_retry_counts[delivery_id] = retry_count + 1
        self._runtime_retrying_ids.add(delivery_id)

        async def retry_later() -> None:
            try:
                await asyncio.sleep(max(0.0, delay))
                if not self._running:
                    return
                current = self.outbox_store.get(delivery_id)
                if current is None or current.status != "failed":
                    return
                if time.time() - current.created_at >= self._runtime_retry_max_age_s:
                    self.outbox_store.mark_expired(delivery_id)
                    logger.warning("出站消息重试已过期: %s", delivery_id)
                    return
                self.outbound.publish(message)
                logger.info(
                    "已安排运行期出站重试: delivery_id=%s retry=%d",
                    delivery_id,
                    retry_count + 1,
                )
            except asyncio.CancelledError:
                raise
            finally:
                self._runtime_retrying_ids.discard(delivery_id)
                self._runtime_retry_tasks.discard(asyncio.current_task())

        task = asyncio.create_task(retry_later())
        self._runtime_retry_tasks.add(task)

    def _finish_delivery(
        self,
        message: OutboundMessage,
        *,
        delivered: bool,
        attempts: int,
        error: str,
        uncertain: bool = False,
        retryable: bool = True,
    ) -> None:
        """提交出站终态并通知等待方。"""

        receipt = DeliveryReceipt(
            delivery_id=message.delivery_id,
            delivered=delivered,
            attempts=attempts,
            error=error,
            uncertain=uncertain,
            retryable=retryable,
        )
        if self.outbox_store is not None:
            if delivered:
                self.outbox_store.mark_delivered(message.delivery_id)
                self._runtime_retry_counts.pop(message.delivery_id, None)
            elif uncertain or not retryable:
                if uncertain:
                    self.outbox_store.mark_unknown(message.delivery_id, error)
                else:
                    self.outbox_store.mark_failed(message.delivery_id, error)
                self._runtime_retry_counts.pop(message.delivery_id, None)
            else:
                self.outbox_store.mark_failed(message.delivery_id, error)
        self.outbound_port.complete(receipt)

    def _get_subscribers(self, channel: str) -> list[Callable[[OutboundMessage], None]]:
        with self.outbound._lock:
            return list(self.outbound._subscribers.get(channel, []))

    @property
    def running(self) -> bool:
        return self._running


def _resolve_chat_id(
    channel: str,
    session_id: str,
    metadata: dict[str, object],
) -> str:
    """从旧调用携带的渠道元数据中推导目标标识。"""

    if channel == "telegram":
        return str(metadata.get("telegram_chat_id") or session_id)
    if channel in {"qq", "qqbot"}:
        return str(
            metadata.get("qq_group_id")
            or metadata.get("qq_user_id")
            or session_id
        )
    return session_id
