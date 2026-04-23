from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.runtime.service import RuntimeService


@dataclass(slots=True)
class DashboardRuntimeSnapshot:
    turn_summary: dict[str, Any]
    proactive_summary: dict[str, Any]
    jobs_summary: dict[str, Any]
    subagent_summary: dict[str, Any]
    memory_retrieval_summary: dict[str, Any]
    runtime: dict[str, Any]


def build_runtime_snapshot(
    dashboard: InMemoryDashboardStore,
    runtime_service: RuntimeService | None = None,
) -> DashboardRuntimeSnapshot:
    snap = dashboard.snapshot()
    retrieval_events = [e for e in snap.turns if e.get("type") == "retrieval"]
    runtime_part = (
        asdict(runtime_service.snapshot())
        if runtime_service is not None
        else {"runtimes": [], "metrics": {}, "event_summary": {}}
    )
    return DashboardRuntimeSnapshot(
        turn_summary={"count": len(snap.turns), "last": snap.turns[-1] if snap.turns else None},
        proactive_summary={
            "count": len(snap.proactive),
            "last": snap.proactive[-1] if snap.proactive else None,
        },
        jobs_summary={"count": len(snap.jobs), "last": snap.jobs[-1] if snap.jobs else None},
        subagent_summary={
            "count": len(snap.subagents),
            "last": snap.subagents[-1] if snap.subagents else None,
        },
        memory_retrieval_summary={
            "retrieval_count": len(retrieval_events),
            "last_retrieval": retrieval_events[-1] if retrieval_events else None,
        },
        runtime=runtime_part,
    )
