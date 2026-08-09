"""MCP 数据源轮询模块。"""

import asyncio
import logging
from typing import TYPE_CHECKING

from application.proactive.infra.mcp_pool import McpClientPool
from application.capabilities.plugins.proactive import RegisteredProactiveSource

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def source_key(source: RegisteredProactiveSource) -> str:
    """获取数据源的稳定身份：plugin_id:source_id"""
    return source.source_key


async def poll_source_async(pool: McpClientPool, source: RegisteredProactiveSource) -> None:
    """调用 MCP 源的 poll_tool 进行轮询。"""
    if not source.spec.poll_tool:
        return
    
    key = source_key(source)
    try:
        await pool.call(source.spec.server, source.spec.poll_tool)
        logger.info("[proactive.source] poll 完成: %s", key)
    except Exception as e:
        logger.warning("[proactive.source] poll 失败 %s: %s", key, e)


class McpPollingModule:
    """MCP 数据源轮询模块。
    
    为带 poll_tool 的数据源创建周期任务，定期调用 poll_tool 更新上游缓存。
    """
    
    def __init__(
        self,
        pool: McpClientPool,
        sources: list[RegisteredProactiveSource],
    ) -> None:
        self._pool = pool
        self._sources = [source for source in sources if source.spec.poll_tool]
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []
    
    async def start(self) -> None:
        """启动轮询模块，为每个带 poll_tool 的数据源创建周期任务。"""
        self._running = True
        try:
            for source in self._sources:
                await self._poll_once(source)
                ready = asyncio.Event()
                self._tasks.append(
                    asyncio.create_task(
                        self._poll_loop(source, ready),
                        name=f"proactive_poll:{source_key(source)}",
                    )
                )
                _ = await ready.wait()
        except BaseException:
            await self.stop()
            raise
    
    async def stop(self) -> None:
        """停止所有轮询任务。"""
        self._running = False
        for task in self._tasks:
            _ = task.cancel()
        if self._tasks:
            _ = await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
    
    async def _poll_once(self, source: RegisteredProactiveSource) -> None:
        """执行一次轮询。"""
        await poll_source_async(self._pool, source)
    
    async def _poll_loop(
        self,
        source: RegisteredProactiveSource,
        ready: asyncio.Event,
    ) -> None:
        """轮询循环。"""
        ready.set()
        interval = max(1, int(source.spec.poll_interval_seconds))
        while self._running:
            await asyncio.sleep(interval)
            if self._running:
                await self._poll_once(source)
