"""消费入站消息并编排对话回合的后台工作器。"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections import deque
from typing import Protocol

from application.conversation.domain.messages import IncomingMessage
from application.ports.message_consumer import MessageConsumer, ReceivedMessage


class ChatProcessor(Protocol):
    """执行单个对话回合的应用服务。"""

    async def process_async(self, message: IncomingMessage) -> None:
        """处理一条已经完成协议转换的入站消息。"""

        ...


class ChatWorker:
    """维持会话顺序，并让不同会话并行处理。"""

    def __init__(
        self,
        consumer: MessageConsumer,
        processor: ChatProcessor,
        *,
        poll_interval_ms: int = 100,
    ) -> None:
        self._consumer = consumer
        self._processor = processor
        self._poll_interval_ms = max(1, poll_interval_ms)
        self._running = False
        self._active_by_conversation: dict[str, asyncio.Task[None]] = {}
        self._pending_by_conversation: dict[str, deque[ReceivedMessage]] = {}
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
        finally:
            tasks = tuple(self._active_by_conversation.values())
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._active_by_conversation.clear()
            self._pending_by_conversation.clear()

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
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        if thread is None or not thread.is_alive():
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

    def _enqueue_or_start(self, message: ReceivedMessage) -> None:
        conversation_id = message.conversation_id
        if conversation_id in self._active_by_conversation:
            self._pending_by_conversation.setdefault(conversation_id, deque()).append(
                message
            )
            return
        self._start(message)

    def _start(self, message: ReceivedMessage) -> None:
        task = asyncio.create_task(self._process_one(message))
        conversation_id = message.conversation_id
        self._active_by_conversation[conversation_id] = task
        task.add_done_callback(
            lambda completed, owner=conversation_id: self._finish(completed, owner)
        )

    async def _process_one(self, message: ReceivedMessage) -> None:
        inbound = IncomingMessage(
            channel=message.channel,
            conversation_id=message.conversation_id,
            text=message.text,
            sender_id=message.sender_id,
            media=message.media,
            metadata=dict(message.metadata),
        )
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
