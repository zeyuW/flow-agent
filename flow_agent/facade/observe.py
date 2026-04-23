from dataclasses import dataclass
from typing import Any

from flow_agent.dashboard.store import InMemoryDashboardStore


@dataclass(slots=True)
class ObserveFacade:
    dashboard: InMemoryDashboardStore

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        snap = self.dashboard.snapshot()
        return {
            "turns": snap.turns,
            "tools": snap.tools,
            "proactive": snap.proactive,
            "jobs": snap.jobs,
            "subagents": snap.subagents,
        }
