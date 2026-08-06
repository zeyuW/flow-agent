"""被动对话的并发与会话顺序编排。"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections import deque
from typing import Protocol

from application.conversation.domain.messages import IncomingMessage

# 被动新链路的工作器集中在 chat_worker.py。此 re-export 仅用于尚未迁移的
# 旧测试和内部运行单元，避免在迁移期间复制两份并发编排逻辑。
from .chat_worker import ChatWorker


class IncomingMessageSource(Protocol):
    """向对话应用提供已完成协议适配的入站消息。"""

    async def receive(self, poll_interval_ms: int) -> IncomingMessage:
        """等待下一条入站消息。"""

        ...


class ConversationProcessor(Protocol):
    """执行单个对话回合的应用端口。

    新对话管道应提供 `process_async`；运行器仍兼容迁移期的同步 `process`。
    """

    async def process(self, message: IncomingMessage) -> None:
        """处理一条消息直到回合终态。"""

        ...


class ConversationRunner:
    """维持同一会话 FIFO、不同会话可并行的被动对话运行器。"""

    def __init__(
        self,
        source: IncomingMessageSource,
        processor: ConversationProcessor,
        *,
        poll_interval_ms: int = 100,
    ) -> None:
        self._source = source
        self._processor = processor
        self._poll_interval_ms = max(1, poll_interval_ms)
        self._running = False
        self._active_by_conversation: dict[str, asyncio.Task[None]] = {}
        self._pending_by_conversation: dict[str, deque[IncomingMessage]] = {}
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def run_forever(self) -> None:
        """持续领取消息，并让不同会话独立推进。"""

        self._running = True
        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(
                        self._source.receive(self._poll_interval_ms),
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
        """请求停止，并在超时后取消仍未完成的回合。"""

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

    def is_processing(self, conversation_id: str) -> bool:
        """供其他业务判断该会话是否有尚未结束的被动回合。"""

        task = self._active_by_conversation.get(conversation_id)
        return task is not None and not task.done()

    def start_background(self) -> None:
        """在独立线程启动事件循环，供同步进程入口使用。"""

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
        """从同步入口停止后台事件循环，并等待线程退出。"""

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
        """返回运行器是否仍在领取新消息。"""

        return self._running

    @property
    def active_task_count(self) -> int:
        """返回当前正在处理的会话数量。"""

        return len(self._active_by_conversation)

    @property
    def pending_message_count(self) -> int:
        """返回尚未开始处理的消息总数。"""

        return sum(len(items) for items in self._pending_by_conversation.values())

    def _enqueue_or_start(self, message: IncomingMessage) -> None:
        conversation_id = message.conversation_id
        if conversation_id in self._active_by_conversation:
            self._pending_by_conversation.setdefault(conversation_id, deque()).append(
                message
            )
            return
        self._start(message)

    def _start(self, message: IncomingMessage) -> None:
        task = asyncio.create_task(self._process_one(message))
        conversation_id = message.conversation_id
        self._active_by_conversation[conversation_id] = task
        task.add_done_callback(
            lambda completed, owner=conversation_id: self._finish(completed, owner)
        )

    async def _process_one(self, message: IncomingMessage) -> None:
        """调用对话处理器，优先使用不会阻塞事件循环的异步入口。"""

        process_async = getattr(self._processor, "process_async", None)
        if callable(process_async):
            result = process_async(message)
            if inspect.isawaitable(result):
                await result
            return

        process = getattr(self._processor, "process", None)
        if not callable(process):
            raise TypeError("对话处理器必须提供 process_async 或 process")
        result = process(message)
        if inspect.isawaitable(result):
            await result

    def _finish(self, task: asyncio.Task[None], conversation_id: str) -> None:
        """一个回合结束后，才允许同会话中的下一条消息开始。"""

        self._active_by_conversation.pop(conversation_id, None)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            # 回合异常已经由具体处理器记录；FIFO 队列仍须继续推进。
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
