"""Agent 主循环：作为 MessageBus 入站队列的消费者。

AgentLoop 持续从 MessageBus 拉取 InboundItem，
并调用 PassiveTurnPipeline.process 处理每条消息。
"""

import logging
import threading
import time

from flow_agent.channels.models import InboundMessage
from flow_agent.core.passive_turn_pipeline import PassiveTurnPipeline
from flow_agent.messaging.message_bus import MessageBus

logger = logging.getLogger(__name__)


class AgentLoop:
    """Agent 主循环。

    作为 MessageBus 入站队列的消费者，
    持续拉取消息并交给 PassiveTurnPipeline 处理。

    支持两种运行模式：
    - run_once(): 处理一条消息后返回
    - run_forever(): 持续轮询处理（阻塞）
    """

    def __init__(
        self,
        message_bus: MessageBus,
        pipeline: PassiveTurnPipeline,
        poll_interval_ms: int = 100,
    ) -> None:
        self._bus = message_bus
        self._pipeline = pipeline
        self._poll_interval = poll_interval_ms / 1000.0
        self._running = False
        self._thread: threading.Thread | None = None

    def run_once(self) -> bool:
        """处理一条入站消息（非阻塞），返回是否处理了消息。"""
        inbound = self._bus.consume_inbound()
        if inbound is None:
            return False
        self._process(inbound)
        return True

    def run_forever(self) -> None:
        """持续轮询处理入站消息（阻塞）。"""
        self._running = True
        logger.info("agent loop started, polling every %dms", int(self._poll_interval * 1000))
        try:
            while self._running:
                processed = self.run_once()
                if not processed:
                    time.sleep(self._poll_interval)
        except KeyboardInterrupt:
            logger.info("agent loop interrupted")
        finally:
            self._running = False

    def start_background(self) -> None:
        """在后台线程中启动 AgentLoop。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("agent loop background thread started")

    def stop(self) -> None:
        """停止 AgentLoop。"""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("agent loop stopped")

    def _loop(self) -> None:
        while self._running:
            processed = self.run_once()
            if not processed:
                time.sleep(self._poll_interval)

    def _process(self, inbound: InboundMessage) -> None:
        """处理单条入站消息。"""
        logger.info(
            "agent loop processing: channel=%s session=%s",
            inbound.channel,
            inbound.session_id,
        )
        try:
            self._pipeline.process(inbound)
        except Exception:
            logger.exception("agent loop pipeline failed")

    @property
    def running(self) -> bool:
        return self._running