"""Agent 主循环：作为 MessageBus 入站队列的消费者。

AgentLoop 持续从 MessageBus 阻塞式消费入站消息，
为每个消息通过 asyncio.create_task() 创建独立异步任务，
确保一个会话的长推理不会阻塞其他会话的响应。

流程：
  1. 从 MessageBus 阻塞消费 InboundItem
  2. 检查 _processing 状态，防止同一会话并发处理
  3. 通过 asyncio.create_task() 创建独立任务
  4. 任务中发布 TurnStarted 事件 → 委托给 Pipeline 处理
"""

import asyncio
import logging
import time

from flow_agent.channels.models import InboundMessage
from flow_agent.core.passive_turn_pipeline import PassiveTurnPipeline
from flow_agent.messaging.message_bus import MessageBus
from flow_agent.messaging.event_bus import EventBus, Event

logger = logging.getLogger(__name__)


class ProcessingState:
    """会话处理状态管理。

    防止同一会话的消息并发处理。
    当会话已有正在处理的任务时，新消息会被合并到现有处理流程中。
    """

    def __init__(self) -> None:
        self._processing: dict[str, asyncio.Task | None] = {}

    def is_processing(self, session_id: str) -> bool:
        """检查指定会话是否正在处理中。"""
        task = self._processing.get(session_id)
        return task is not None and not task.done()

    def set_processing(self, session_id: str, task: asyncio.Task) -> None:
        """标记会话为处理中。"""
        self._processing[session_id] = task

    def clear_processing(self, session_id: str) -> None:
        """清除会话的处理状态。"""
        self._processing.pop(session_id, None)

    def wait_for_processing(self, session_id: str, timeout: float = 30.0) -> bool:
        """等待指定会话的当前处理完成（同步阻塞）。"""
        task = self._processing.get(session_id)
        if task is None or task.done():
            return True
        try:
            # 在事件循环中等待任务完成
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return False  # 不能在同一事件循环中阻塞等待
            return True
        except RuntimeError:
            return False


class AgentLoop:
    """Agent 主循环。

    作为 MessageBus 入站队列的消费者，
    持续拉取消息并通过 asyncio.create_task() 创建独立处理任务。

    支持两种运行模式：
    - run_once(): 处理一条消息后返回
    - run_forever(): 持续轮询处理（异步阻塞）
    """

    def __init__(
        self,
        message_bus: MessageBus,
        pipeline: PassiveTurnPipeline,
        event_bus: EventBus | None = None,
        poll_interval_ms: int = 100,
    ) -> None:
        self._bus = message_bus
        self._pipeline = pipeline
        self._event_bus = event_bus
        self._poll_interval = poll_interval_ms / 1000.0
        self._running = False
        self._processing = ProcessingState()
        self._active_tasks: set[asyncio.Task] = set()

    def run_once(self) -> bool:
        """处理一条入站消息（同步、非阻塞），返回是否处理了消息。

        用于简单场景或测试。生产环境建议使用 run_forever()。
        """
        inbound = self._bus.consume_inbound()
        if inbound is None:
            return False
        self._process(inbound)
        return True

    async def run_forever(self) -> None:
        """持续异步轮询处理入站消息。

        主循环在 while self._running 中持续运行，
        每次从 MessageBus 获取 InboundItem 后，
        立即通过 asyncio.create_task() 创建独立任务，实现并发处理。
        """
        self._running = True
        logger.info(
            "agent loop started, polling every %dms", int(self._poll_interval * 1000)
        )
        try:
            while self._running:
                inbound = await self._bus.consume_inbound_async(
                    poll_interval_ms=int(self._poll_interval * 1000)
                )
                if inbound is None:
                    continue

                # 检查是否已有同一 session 的处理任务
                if self._processing.is_processing(inbound.session_id):
                    logger.info(
                        "session %s already processing, skipping new message",
                        inbound.session_id,
                    )
                    continue

                # 创建独立任务，实现并发处理
                task = asyncio.create_task(self._process_async(inbound))
                self._processing.set_processing(inbound.session_id, task)
                self._active_tasks.add(task)
                task.add_done_callback(self._on_task_done)
        except asyncio.CancelledError:
            logger.info("agent loop cancelled")
        except Exception:
            logger.exception("agent loop error")
        finally:
            self._running = False
            # 等待所有活跃任务完成
            if self._active_tasks:
                logger.info("waiting for %d active tasks to finish", len(self._active_tasks))
                await asyncio.gather(*self._active_tasks, return_exceptions=True)

    async def stop(self) -> None:
        """停止 AgentLoop。"""
        self._running = False
        # 等待活跃任务
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        logger.info("agent loop stopped")

    def _on_task_done(self, task: asyncio.Task) -> None:
        """任务完成回调：清理状态。"""
        self._active_tasks.discard(task)
        # 清理 processing 状态
        for session_id, t in list(self._processing._processing.items()):
            if t is task:
                self._processing.clear_processing(session_id)
                break

    def _process(self, inbound: InboundMessage) -> None:
        """同步处理单条入站消息（兼容旧接口）。

        发布 TurnStarted 事件后委托给 Pipeline。
        """
        self._publish_turn_started(inbound)
        logger.info(
            "agent loop processing: channel=%s session=%s",
            inbound.channel,
            inbound.session_id,
        )
        try:
            self._pipeline.process(inbound)
        except Exception:
            logger.exception("agent loop pipeline failed")

    async def _process_async(self, inbound: InboundMessage) -> None:
        """异步处理单条入站消息。

        1. 检查中断状态（/stop 续跑）
        2. 发布 TurnStarted 事件
        3. 委托给 Pipeline 执行 6 阶段处理
        """
        self._publish_turn_started(inbound)
        logger.info(
            "agent loop processing async: channel=%s session=%s",
            inbound.channel,
            inbound.session_id,
        )
        try:
            self._pipeline.process(inbound)
        except Exception:
            logger.exception("agent loop async pipeline failed")
        finally:
            self._processing.clear_processing(inbound.session_id)

    def _publish_turn_started(self, inbound: InboundMessage) -> None:
        """发布 TurnStarted 事件，通知插件和观察者新处理周期开始。"""
        if self._event_bus is not None:
            event = Event(
                event_type="turn_started",
                session_id=inbound.session_id,
                payload={
                    "channel": inbound.channel,
                    "user_input": inbound.text,
                },
            )
            self._event_bus.publish(event)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def active_task_count(self) -> int:
        return len(self._active_tasks)