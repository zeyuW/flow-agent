"""ProactiveLoop: adaptive interval loop with MCP pool connection (spec 1)."""

import asyncio
import logging
import math
import time

from flow_agent.proactive.mcp_pool import McpClientPool
from flow_agent.proactive.proactive_pipeline import ProactiveTurnPipeline

logger = logging.getLogger(__name__)


class ProactiveLoop:
    """Main proactive loop: adaptive intervals, MCP pool, tick dispatch (spec 1c-1e)."""

    def __init__(
        self,
        pipeline: ProactiveTurnPipeline,
        mcp_pool: McpClientPool,
        *,
        chat_id: str = "",
        min_interval: float = 30.0,
        max_interval: float = 300.0,
        is_busy_fn = None
    ) -> None:
        self._pipeline = pipeline
        self._pool = mcp_pool
        self._chat_id = chat_id
        self._min_interval = min_interval
        self._max_interval = max_interval
        self._is_busy_fn = is_busy_fn
        self._running = False
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        """Start the proactive loop (spec 1c-1e)."""
        self._running = True

        # spec 1d: connect MCP pool
        try:
            await self._pool.connect_all()
        except Exception:
            logger.exception("MCP pool connect failed")

        # spec 1e: main adaptive loop
        await self._run_loop()

    async def _run_loop(self) -> None:
        interval = self._max_interval
        base_score = 0.0

        is_busy = self._is_busy_fn() if self._is_busy_fn else False
        while self._running:
            tick = await self._pipeline.run(
                chat_id=self._chat_id,
                base_score=base_score,
                is_busy=is_busy,
            )

            # spec 1d: adaptive interval from gate result
            if tick.gate_result:
                interval = tick.gate_result.next_interval
                if tick.gate_result.passed:
                    base_score = min(1.0, base_score + 0.05)
                else:
                    base_score = max(0.0, base_score - 0.02)

            interval = max(self._min_interval, min(self._max_interval, interval))
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        await self._pool.close_all()

    async def start_background(self) -> asyncio.Task:
        """Start the loop as a background task (spec 1b)."""
        self._task = asyncio.create_task(self.run(), name="proactive_loop")
        return self._task
