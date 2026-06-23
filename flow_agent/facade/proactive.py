"""Facade for proactive runtime operations."""

from dataclasses import dataclass
import asyncio

from flow_agent.proactive.proactive_loop import ProactiveLoop


@dataclass(slots=True)
class ProactiveFacade:
    """Facade for proactive runtime operations."""

    loop: ProactiveLoop

    async def start_background(self) -> asyncio.Task:
        return await self.loop.start_background()

    async def stop(self) -> None:
        await self.loop.stop()

    def is_running(self) -> bool:
        return self.loop._running
