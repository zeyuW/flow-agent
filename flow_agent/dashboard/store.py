from dataclasses import dataclass
from typing import Any

from flow_agent.observe.store import UnifiedEventStore

@dataclass(slots=True)
class DashboardSnapshot:
    turns: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    proactive: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    subagents: list[dict[str, Any]]


class InMemoryDashboardStore:
    """Dashboard-compatible view over unified event store."""

    def __init__(self, capacity: int = 200) -> None:
        self._events = UnifiedEventStore(capacity=capacity)

    def record(self, event: dict[str, Any]) -> None:
        self._events.record(event)

    def snapshot(self) -> DashboardSnapshot:
        snapshot = self._events.snapshot()
        return DashboardSnapshot(
            turns=snapshot.turns,
            tools=snapshot.tools,
            proactive=snapshot.proactive,
            jobs=snapshot.jobs,
            subagents=snapshot.subagents,
        )

    def all_events(self) -> list[dict[str, Any]]:
        return self._events.snapshot().all_events

