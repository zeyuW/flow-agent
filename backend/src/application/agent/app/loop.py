"""Agent 通用消息循环。

本模块负责消费消息、维持同一会话的 FIFO 顺序、并发处理不同会话，
以及在停止时回收异步任务。具体业务消息由 ``message_mapper`` 转换，
具体业务处理由 ``processor`` 提供，因此不依赖 passive 或 proactive。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol
from uuid import uuid4

from infra.bus.event import Event
from infra.bus.types import MessageConsumer, ReceivedMessage

logger = logging.getLogger(__name__)


class AgentProcessor(Protocol):
    """执行单个 Agent 回合的应用服务。"""

    async def process_async(self, message: Any) -> None:
        """处理一条已经完成业务转换的入站消息。"""

        ...


class AgentLoop:
    """维持会话顺序，并让不同会话并行处理。"""

    def __init__(
        self,
        consumer: MessageConsumer,
        processor: AgentProcessor,
        *,
        event_bus: Any | None = None,
        message_mapper: Callable[[ReceivedMessage], Any] | None = None,
        poll_interval_ms: int = 100,
    ) -> None:
        self._consumer = consumer
        self._processor = processor
        self._event_bus = event_bus
        self._message_mapper = message_mapper or (lambda message: message)
        self._poll_interval_ms = max(1, poll_interval_ms)
        self._running = False
        self._active_by_conversation: dict[str, asyncio.Task[None]] = {}
        self._pending_by_conversation: dict[str, deque[ReceivedMessage]] = {}
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def run_forever(self) -> None:
        """持续消费入站消息。"""

        self._running = True
        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(
                        self._consumer.receive(self._poll_interval_ms),
                        timeout=max(self._poll_interval_ms / 1000.0, 0.05),
                    )
                except asyncio.TimeoutError:
                    continue
                self._enqueue_or_start(message)
        except asyncio.CancelledError:
            logger.info("AgentLoop 被取消")
        finally:
            tasks = tuple(self._active_by_conversation.values())
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._active_by_conversation.clear()
            self._pending_by_conversation.clear()
            self._active_tasks.clear()

    def run_once(self) -> bool:
        """同步处理一条消息，供命令行入口和单元测试使用。"""

        consume = getattr(self._consumer, "consume_inbound", None)
        if not callable(consume):
            raise RuntimeError("当前消息消费者不支持同步处理")
        raw_message = consume()
        if raw_message is None:
            return False
        message = _received_message_from(raw_message)
        self._publish_turn_started(message)
        inbound = self._message_mapper(message)
        try:
            process = getattr(self._processor, "process", None)
            if callable(process):
                result = process(inbound)
            else:
                result = self._processor.process_async(inbound)
            if inspect.isawaitable(result):
                asyncio.run(result)
        except Exception:
            logger.exception("AgentLoop 同步处理失败")
            return False
        return True

    async def stop(self, timeout: float = 5.0) -> None:
        """请求停止并等待正在处理的回合。"""

        self._running = False
        tasks = tuple(self._active_by_conversation.values())
        if not tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=max(0.0, timeout),
            )
        except asyncio.TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def start_background(self) -> None:
        """在独立线程启动工作器。"""

        if self._thread is not None and self._thread.is_alive():
            return

        def run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.run_forever())
            finally:
                self._loop = None
                loop.close()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop_background(self, timeout: float = 5.0) -> None:
        """从同步入口停止工作器线程。"""

        loop = self._loop
        thread = self._thread
        if loop is not None and not loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(self.stop(timeout), loop)
            future.result(timeout=max(1.0, timeout + 1.0))
        self.join(timeout=max(0.0, timeout))

    def join(self, timeout: float | None = None) -> None:
        """等待后台线程退出并回收线程引用。"""

        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return
        thread.join(timeout=timeout)
        if not thread.is_alive():
            self._thread = None

    @property
    def running(self) -> bool:
        """返回工作器是否仍在消费消息。"""

        return self._running

    def is_processing(self, conversation_id: str) -> bool:
        """返回指定会话是否仍有未完成的回合。"""

        task = self._active_by_conversation.get(conversation_id)
        return task is not None and not task.done()

    @property
    def active_task_count(self) -> int:
        """返回当前正在执行的会话回合数量。"""

        return sum(not task.done() for task in self._active_by_conversation.values())

    @property
    def pending_message_count(self) -> int:
        """返回所有会话尚未开始处理的消息数量。"""

        return sum(len(items) for items in self._pending_by_conversation.values())

    def _enqueue_or_start(self, message: ReceivedMessage) -> None:
        conversation_id = message.conversation_id
        if conversation_id in self._active_by_conversation:
            self._pending_by_conversation.setdefault(conversation_id, deque()).append(
                message
            )
            return
        self._start(message)

    def _start(self, message: ReceivedMessage) -> None:
        task = asyncio.create_task(self._process_async(message))
        conversation_id = message.conversation_id
        self._active_by_conversation[conversation_id] = task
        self._active_tasks.add(task)
        task.add_done_callback(
            lambda completed, owner=conversation_id: self._finish(completed, owner)
        )

    async def _process_async(self, message: ReceivedMessage) -> None:
        inbound = self._message_mapper(message)
        self._publish_turn_started(message)
        try:
            process_async = getattr(self._processor, "process_async", None)
            if callable(process_async):
                result = process_async(inbound)
            else:
                result = self._processor.process(inbound)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._consumer.nack(message.message_id, retry=True)
            raise
        else:
            await self._consumer.ack(message.message_id)

    def _finish(self, task: asyncio.Task[None], conversation_id: str) -> None:
        self._active_by_conversation.pop(conversation_id, None)
        self._active_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            pass
        pending = self._pending_by_conversation.get(conversation_id)
        if not pending:
            self._pending_by_conversation.pop(conversation_id, None)
            return
        next_message = pending.popleft()
        if not pending:
            self._pending_by_conversation.pop(conversation_id, None)
        if self._running:
            self._start(next_message)

    def _publish_turn_started(self, message: ReceivedMessage) -> None:
        """通知观察者一个 Agent 回合已经开始。"""

        if self._event_bus is None:
            return
        self._event_bus.publish(
            Event(
                event_type="turn_started",
                session_id=message.conversation_id,
                payload={
                    "channel": message.channel,
                    "user_input": message.text,
                },
            )
        )


def _received_message_from(message: Any) -> ReceivedMessage:
    """把同步入站消息包装成 AgentLoop 使用的统一消息。"""

    if isinstance(message, ReceivedMessage):
        return message
    return ReceivedMessage(
        message_id=uuid4().hex,
        kind="conversation.input",
        channel=str(message.channel),
        conversation_id=str(message.session_id),
        text=str(message.text),
        sender_id=str(getattr(message, "sender", "")),
        media=tuple(getattr(message, "media", ()) or ()),
        metadata=dict(getattr(message, "metadata", {}) or {}),
        chat_id=str(getattr(message, "chat_id", "")),
    )
