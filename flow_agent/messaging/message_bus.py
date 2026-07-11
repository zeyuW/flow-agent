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
from typing import Callable, Protocol

from flow_agent.channels.models import InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)


@dataclass
class InboundQueue:
    """入站消息队列：线程安全的 FIFO 队列。"""

    _queue: deque[InboundMessage] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def publish(self, message: InboundMessage) -> None:
        """向入站队列发布一条消息。"""
        with self._lock:
            self._queue.append(message)
            logger.debug("inbound published: channel=%s session=%s", message.channel, message.session_id)

    def consume_one(self) -> InboundMessage | None:
        """从入站队列消费一条消息（非阻塞）。"""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    async def consume_one_async(self, poll_interval_ms: int = 100) -> InboundMessage | None:
        """从入站队列阻塞消费一条消息（异步，适用于 AgentLoop 主循环）。"""
        while True:
            with self._lock:
                if self._queue:
                    return self._queue.popleft()
            await asyncio.sleep(poll_interval_ms / 1000.0)

    def consume_all(self) -> list[InboundMessage]:
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
    metadata: dict[str, object] = field(default_factory=dict)


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
    def send(self, dispatch: OutboundDispatch) -> None:
        ...


@dataclass
class BusOutboundPort(OutboundPort):
    """OutboundPort 的实现：将 OutboundDispatch 发布到 OutboundQueue。

    AgentLoop/Pipeline 使用此接口投递回复，不直接操作出站队列。
    """
    _queue: OutboundQueue

    def send(self, dispatch: OutboundDispatch) -> None:
        """将 OutboundDispatch 转换为 OutboundMessage 并投递到出站队列。"""
        message = OutboundMessage(
            channel=dispatch.channel,
            session_id=dispatch.session_id,
            text=dispatch.text,
            metadata=dispatch.metadata,
        )
        self._queue.publish(message)


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
    outbound_port: BusOutboundPort = field(init=False)
    _dispatch_task: asyncio.Task | None = field(default=None, repr=False)
    _retry_delay_s: float = 2.0
    _running: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self.outbound_port = BusOutboundPort(_queue=self.outbound)

    def publish_inbound(self, message: InboundMessage) -> None:
        """渠道适配器调用：将入站消息发布到总线。"""
        self.inbound.publish(message)

    def consume_inbound(self) -> InboundMessage | None:
        """AgentLoop 调用：从总线拉取一条入站消息。"""
        return self.inbound.consume_one()

    async def consume_inbound_async(self, poll_interval_ms: int = 100) -> InboundMessage | None:
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
        """停止后台出站分发任务。"""
        self._running = False
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
                    "outbound dispatch: no subscribers for channel=%s, dropping message", channel
                )
                continue

            # 遍历该 channel 的所有订阅者并调用回调
            subscribers = self._get_subscribers(channel)
            logger.debug("found %d subscribers for channel=%s", len(subscribers), channel)
            for callback in subscribers:
                await self._dispatch_with_retry(message, callback)

    async def _dispatch_with_retry(
        self, message: OutboundMessage, callback: Callable[[OutboundMessage], None]
    ) -> None:
        """带容错重试的出站分发。

        - 首次调用失败：等待 2 秒后重试一次
        - 仍然失败：发送降级错误通知给用户，而非静默丢弃
        """
        try:
            result = callback(message)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception(
                "outbound dispatch failed, retrying in %ss", self._retry_delay_s
            )
            await asyncio.sleep(self._retry_delay_s)
            try:
                result = callback(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "outbound dispatch failed after retry, sending fallback error"
                )
                # 发送降级错误通知
                fallback = OutboundMessage(
                    channel=message.channel,
                    session_id=message.session_id,
                    text="抱歉，消息发送失败，请稍后重试。",
                    metadata={
                        **message.metadata,
                        "fallback": True,
                        "original_length": len(message.text),
                    },
                )
                # 尝试发送降级消息（不重试降级消息）
                for cb in self._get_subscribers(message.channel):
                    try:
                        result = cb(fallback)
                        if asyncio.iscoroutine(result):
                            await result
                        break
                    except Exception:
                        logger.exception(
                            "fallback dispatch also failed for channel=%s", message.channel
                        )

    def _get_subscribers(self, channel: str) -> list[Callable[[OutboundMessage], None]]:
        with self.outbound._lock:
            return list(self.outbound._subscribers.get(channel, []))

    @property
    def running(self) -> bool:
        return self._running