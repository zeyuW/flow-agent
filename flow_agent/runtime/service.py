from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from flow_agent.runtime.models import RuntimeHealth, RuntimeServiceSnapshot, RuntimeUnitSnapshot


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeUnit:
    name: str
    start_fn: Callable[[], None] | None = None
    stop_fn: Callable[[], None] | None = None
    health_fn: Callable[[], RuntimeHealth] | None = None
    snapshot_fn: Callable[[], RuntimeUnitSnapshot] | None = None
    restart_policy: str = "manual"

    def start(self) -> None:
        if self.start_fn is not None:
            self.start_fn()

    def stop(self) -> None:
        if self.stop_fn is not None:
            self.stop_fn()

    def health(self) -> RuntimeHealth:
        if self.health_fn is None:
            return RuntimeHealth(
                name=self.name,
                ok=True,
                detail="no health handler",
                status="healthy",
                restart_policy=self.restart_policy,
            )
        health = self.health_fn()
        if not health.restart_policy:
            health.restart_policy = self.restart_policy
        if not health.status:
            health.status = "healthy" if health.ok else "degraded"
        return health

    def snapshot(self) -> RuntimeUnitSnapshot:
        if self.snapshot_fn is None:
            return RuntimeUnitSnapshot(
                name=self.name,
                running=True,
                health="healthy",
                restart_policy=self.restart_policy,
            )
        snap = self.snapshot_fn()
        if not snap.restart_policy:
            snap.restart_policy = self.restart_policy
        if not snap.health:
            snap.health = "healthy" if snap.running else "stopped"
        return snap


@dataclass(slots=True)
class RuntimeService:
    """Unified runtime lifecycle and observability entrypoint."""

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
        return {
            "turn_total": 0,
            "tool_total": 0,
            "proactive_total": 0,
            "job_total": 0,
            "subagent_total": 0,
            "all_events_total": 0,
            "quality": {},
        }

    def _get(self, name: str) -> RuntimeUnit:
        unit = self.units.get(name)
        if unit is None:
            raise ValueError(f"unknown runtime unit: {name}")
        return unit

def create_runtime_service(
    proactive_loop=None,
) -> RuntimeService:
    """Create runtime service instance."""
    service = RuntimeService()
    return service
