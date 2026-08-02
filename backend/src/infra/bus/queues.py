"""线程安全的入站、出站消息队列。

队列只关心消息传输和订阅，不依赖任何业务模块。消息的业务结构由调用方定义，
因此对话、主动触发和渠道适配器可以共享同一套基础设施。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class InboundQueue:
    """线程安全的先进先出入站队列。"""

    _queue: deque[Any] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def publish(self, message: Any) -> None:
        """发布一条入站消息。"""

        with self._lock:
            self._queue.append(message)

    def consume_one(self) -> Any | None:
        """非阻塞消费一条入站消息。"""

        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    async def consume_one_async(self, poll_interval_ms: int = 100) -> Any | None:
        """异步等待并消费一条入站消息。"""

        while True:
            message = self.consume_one()
            if message is not None:
                return message
            await asyncio.sleep(poll_interval_ms / 1000.0)

    def consume_all(self) -> list[Any]:
        """消费并清空当前所有入站消息。"""

        with self._lock:
            messages = list(self._queue)
            self._queue.clear()
            return messages

    @property
    def size(self) -> int:
        """返回当前待消费消息数量。"""

        with self._lock:
            return len(self._queue)


OutboundCallback = Callable[[Any], object | Awaitable[object]]


@dataclass
class OutboundQueue:
    """按渠道分发的线程安全出站队列。"""

    _queue: deque[Any] = field(default_factory=deque)
    _subscribers: dict[str, list[OutboundCallback]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def subscribe(self, channel: str, callback: OutboundCallback) -> None:
        """为渠道注册出站回调，重复注册会被忽略。"""

        with self._lock:
            subscribers = self._subscribers.setdefault(channel, [])
            if callback not in subscribers:
                subscribers.append(callback)

    def unsubscribe(self, channel: str, callback: OutboundCallback) -> None:
        """取消渠道出站回调。"""

        with self._lock:
            subscribers = self._subscribers.get(channel)
            if subscribers is None:
                return
            if callback in subscribers:
                subscribers.remove(callback)
            if not subscribers:
                self._subscribers.pop(channel, None)

    def publish(self, message: Any) -> None:
        """将消息放入出站队列，不触发回调。"""

        with self._lock:
            self._queue.append(message)

    def dispatch(self, message: Any) -> None:
        """将消息入队并同步调用对应渠道的回调。"""

        with self._lock:
            self._queue.append(message)
            subscribers = list(self._subscribers.get(message.channel, []))
        for callback in subscribers:
            try:
                result = callback(message)
                if inspect.isawaitable(result):
                    logger.warning("同步出站分发忽略了异步回调: channel=%s", message.channel)
            except Exception:
                logger.exception("出站回调执行失败: channel=%s", message.channel)

    async def dispatch_async(self, message: Any) -> None:
        """将消息入队并等待对应渠道的回调。"""

        with self._lock:
            self._queue.append(message)
            subscribers = list(self._subscribers.get(message.channel, []))
        for callback in subscribers:
            try:
                result = callback(message)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("异步出站回调执行失败: channel=%s", message.channel)

    def consume_one(self) -> Any | None:
        """非阻塞消费一条出站消息。"""

        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    async def consume_one_async(self, poll_interval_ms: int = 100) -> Any | None:
        """异步等待并消费一条出站消息。"""

        while True:
            message = self.consume_one()
            if message is not None:
                return message
            await asyncio.sleep(poll_interval_ms / 1000.0)

    def drain(self) -> list[Any]:
        """清空并返回当前所有出站消息。"""

        with self._lock:
            messages = list(self._queue)
            self._queue.clear()
            return messages

    @property
    def subscriber_count(self) -> int:
        """返回所有渠道的订阅回调数量。"""

        with self._lock:
            return sum(len(subscribers) for subscribers in self._subscribers.values())

    def has_subscribers(self, channel: str) -> bool:
        """判断指定渠道是否存在订阅回调。"""

        with self._lock:
            return bool(self._subscribers.get(channel))
