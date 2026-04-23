from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.runtime.models import RuntimeHealth, RuntimeServiceSnapshot, RuntimeUnitSnapshot


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeUnit:
    name: str
    start_fn: Callable[[], None] | None = None
    stop_fn: Callable[[], None] | None = None
    health_fn: Callable[[], RuntimeHealth] | None = None
    snapshot_fn: Callable[[], RuntimeUnitSnapshot] | None = None

    def start(self) -> None:
        if self.start_fn is not None:
            self.start_fn()

    def stop(self) -> None:
        if self.stop_fn is not None:
            self.stop_fn()

    def health(self) -> RuntimeHealth:
        if self.health_fn is None:
            return RuntimeHealth(name=self.name, ok=True, detail="no health handler")
        return self.health_fn()

    def snapshot(self) -> RuntimeUnitSnapshot:
        if self.snapshot_fn is None:
            return RuntimeUnitSnapshot(name=self.name, running=True)
        return self.snapshot_fn()


@dataclass(slots=True)
class RuntimeService:
    """Unified runtime lifecycle and observability entrypoint."""

    dashboard: InMemoryDashboardStore
    units: dict[str, RuntimeUnit] = field(default_factory=dict)

    def register(self, unit: RuntimeUnit) -> None:
        self.units[unit.name] = unit

    def start(self, name: str) -> None:
        self._get(name).start()

    def stop(self, name: str) -> None:
        self._get(name).stop()

    def health_check(self) -> list[RuntimeHealth]:
        rows: list[RuntimeHealth] = []
        for unit in self.units.values():
            try:
                rows.append(unit.health())
            except Exception as exc:
                logger.exception("runtime health check failed for %s", unit.name)
                rows.append(RuntimeHealth(name=unit.name, ok=False, detail=str(exc)))
        return rows

    def snapshot(self) -> RuntimeServiceSnapshot:
        runtime_rows: list[RuntimeUnitSnapshot] = []
        for unit in self.units.values():
            try:
                runtime_rows.append(unit.snapshot())
            except Exception as exc:
                runtime_rows.append(
                    RuntimeUnitSnapshot(name=unit.name, running=False, details={"error": str(exc)})
                )
        event_summary = self._event_summary()
        metrics = {
            "runtime_count": len(self.units),
            "healthy_count": sum(1 for h in self.health_check() if h.ok),
            "event_total": event_summary["all_events_total"],
        }
        return RuntimeServiceSnapshot(
            runtimes=runtime_rows,
            metrics=metrics,
            event_summary=event_summary,
        )

    def _event_summary(self) -> dict[str, Any]:
        snap = self.dashboard.snapshot()
        all_events = self.dashboard.all_events()
        return {
            "turn_total": len(snap.turns),
            "tool_total": len(snap.tools),
            "proactive_total": len(snap.proactive),
            "job_total": len(snap.jobs),
            "subagent_total": len(snap.subagents),
            "all_events_total": len(all_events),
        }

    def _get(self, name: str) -> RuntimeUnit:
        unit = self.units.get(name)
        if unit is None:
            raise ValueError(f"unknown runtime unit: {name}")
        return unit
