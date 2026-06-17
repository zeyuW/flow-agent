"""消息总线：实现入站队列、出站队列和发布/订阅机制。

MessageBus 是解耦渠道与核心逻辑的关键组件：
- InboundQueue: 渠道适配器发布消息到此队列
- OutboundQueue: AgentLoop 投递回复到此队列，渠道适配器订阅拉取
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass, field

from flow_agent.channels.models import InboundMessage, OutboundMessage, OutboundSubscriber

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
class OutboundQueue:
    """出站消息队列：支持订阅者模式的出站队列。"""

    _queue: deque[OutboundMessage] = field(default_factory=deque)
    _subscribers: list[OutboundSubscriber] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def subscribe(self, subscriber: OutboundSubscriber) -> None:
        """注册一个出站消息订阅者（通常为渠道适配器）。"""
        with self._lock:
            if subscriber not in self._subscribers:
                self._subscribers.append(subscriber)
                logger.debug("outbound subscriber registered: %s", type(subscriber).__name__)

    def unsubscribe(self, subscriber: OutboundSubscriber) -> None:
        """取消订阅。"""
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def dispatch(self, message: OutboundMessage) -> None:
        """投递一条出站消息：入队并立即推送给所有订阅者。"""
        with self._lock:
            self._queue.append(message)
            subs = list(self._subscribers)
        for sub in subs:
            try:
                sub.on_outbound(message)
            except Exception:
                logger.exception("outbound subscriber %s failed", type(sub).__name__)

    def drain(self) -> list[OutboundMessage]:
        """清空并返回到目前为止入队的消息。"""
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


@dataclass
class MessageBus:
    """消息总线：解耦渠道和核心逻辑的中心枢纽。

    提供两个方向的队列：
    - inbound: 渠道 → 核心
    - outbound: 核心 → 渠道
    """

    inbound: InboundQueue = field(default_factory=InboundQueue)
    outbound: OutboundQueue = field(default_factory=OutboundQueue)

    def publish_inbound(self, message: InboundMessage) -> None:
        """渠道适配器调用：将入站消息发布到总线。"""
        self.inbound.publish(message)

    def consume_inbound(self) -> InboundMessage | None:
        """AgentLoop 调用：从总线拉取一条入站消息。"""
        return self.inbound.consume_one()

    def subscribe_outbound(self, subscriber: OutboundSubscriber) -> None:
        """渠道适配器调用：订阅出站消息。"""
        self.outbound.subscribe(subscriber)

    def dispatch_outbound(self, message: OutboundMessage) -> None:
        """AgentLoop 调用：投递出站回复。"""
        self.outbound.dispatch(message)