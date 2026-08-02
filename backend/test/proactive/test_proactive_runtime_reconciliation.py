from __future__ import annotations

import asyncio

import pytest

from modules.proactive.application.lifecycle import ProactiveLifecycle
from modules.proactive.application.mcp_polling import McpPollingModule
from modules.proactive.domain.models import AgentTick
from modules.proactive.application.loop import ProactiveLoop
from modules.proactive.domain.specs import RegisteredProactiveSource, ProactiveSourceSpecImpl


class _Pool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def connect_all(self) -> None:
        return None

    async def close_all(self) -> None:
        return None

    async def call(self, server: str, tool: str, params=None):
        del params
        self.calls.append((server, tool))
        return None


class _Pipeline:
    def __init__(self) -> None:
        self._proactive_sources: list[RegisteredProactiveSource] = []
        self._lifecycle: ProactiveLifecycle | None = None

    def replace_contributions(
        self,
        sources: list[RegisteredProactiveSource],
        lifecycle: ProactiveLifecycle,
    ) -> None:
        self._proactive_sources = list(sources)
        self._lifecycle = lifecycle


class _TickPipeline(_Pipeline):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0

    async def run(self, *, chat_id: str, base_score: float, is_busy: bool):
        del chat_id, base_score, is_busy
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        return AgentTick(chat_id="test")


def _source(source_id: str, *, poll: bool = False) -> RegisteredProactiveSource:
    return RegisteredProactiveSource(
        plugin_id="plugin",
        spec=ProactiveSourceSpecImpl(
            id=source_id,
            channels=("content",),
            server=f"server-{source_id}",
            fetch_tool="fetch",
            poll_tool="poll" if poll else None,
            poll_interval_seconds=1,
        ),
    )


def test_reconcile_contributions_replaces_pipeline_snapshot():
    pipeline = _Pipeline()
    loop = ProactiveLoop(pipeline, _Pool())
    source = _source("new")

    asyncio.run(loop.reconcile_contributions([source], []))

    assert pipeline._proactive_sources == [source]
    assert pipeline._lifecycle is not None


def test_reconcile_compile_failure_keeps_previous_snapshot():
    pipeline = _Pipeline()
    loop = ProactiveLoop(pipeline, _Pool())
    previous = _source("old")
    asyncio.run(loop.reconcile_contributions([previous], []))
    old_lifecycle = pipeline._lifecycle

    class InvalidModule:
        slot = "broken"

    with pytest.raises(ValueError):
        asyncio.run(loop.reconcile_contributions([_source("new")], [InvalidModule()]))

    assert pipeline._proactive_sources == [previous]
    assert pipeline._lifecycle is old_lifecycle


def test_reconcile_replaces_and_stops_old_polling_tasks():
    async def scenario() -> None:
        pool = _Pool()
        pipeline = _Pipeline()
        loop = ProactiveLoop(pipeline, pool)
        loop._running = True
        old_polling = McpPollingModule(pool, [_source("old", poll=True)])
        await old_polling.start()
        loop._polling_module = old_polling

        await loop.reconcile_contributions([_source("new", poll=True)], [])

        assert loop._polling_module is not old_polling
        assert all(task.done() for task in old_polling._tasks)
        await loop._polling_module.stop()
        loop._running = False

    asyncio.run(scenario())


def test_reconcile_and_tick_are_mutually_exclusive():
    async def scenario() -> None:
        pipeline = _TickPipeline()
        loop = ProactiveLoop(pipeline, _Pool())
        loop._running = True
        loop._refresh_lock = asyncio.Lock()

        await asyncio.gather(
            loop._run_single_tick(),
            loop.reconcile_contributions([_source("new")], []),
        )

        assert pipeline.max_active == 1
        loop._running = False

    asyncio.run(scenario())
