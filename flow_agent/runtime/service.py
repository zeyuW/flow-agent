from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
            "quality": self._quality_metrics(all_events),
        }

    def _quality_metrics(self, all_events: list[dict[str, Any]]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(hours=24)

        def _parse_ts(event: dict[str, Any]) -> datetime | None:
            raw = event.get("timestamp")
            if not raw:
                return None
            try:
                return datetime.fromisoformat(str(raw))
            except ValueError:
                return None

        events_1h: list[dict[str, Any]] = []
        events_24h: list[dict[str, Any]] = []
        for event in all_events:
            ts = _parse_ts(event)
            if ts is None:
                continue
            if ts >= day_ago:
                events_24h.append(event)
            if ts >= one_hour_ago:
                events_1h.append(event)

        def _aggregate(events: list[dict[str, Any]]) -> dict[str, Any]:
            retrieval_total = 0
            retrieval_hit = 0
            tool_selection_total = 0
            tool_selected_sum = 0
            tool_available_sum = 0
            tool_result_total = 0
            tool_result_failed = 0
            proactive_sent = 0
            proactive_block_reasons: dict[str, int] = {}

            for event in events:
                event_type = str(event.get("type") or "")
                if event_type == "retrieval":
                    retrieval_total += 1
                    items = int(event.get("items") or 0)
                    if items > 0:
                        retrieval_hit += 1
                elif event_type == "tool_selection":
                    tool_selection_total += 1
                    tool_selected_sum += int(event.get("selected") or 0)
                    tool_available_sum += int(event.get("available") or 0)
                elif event_type == "tool_result":
                    tool_result_total += 1
                    status = str(event.get("status") or "ok")
                    if status != "ok":
                        tool_result_failed += 1
                elif event_type == "proactive_sent":
                    proactive_sent += 1
                elif event_type in {"proactive_judge", "proactive_decision", "proactive_tick_skipped"}:
                    reason = str(event.get("reason") or "unknown")
                    proactive_block_reasons[reason] = proactive_block_reasons.get(reason, 0) + 1

            tool_selection_avg = (tool_selected_sum / tool_selection_total) if tool_selection_total else 0.0
            tool_selection_coverage = (
                tool_selected_sum / tool_available_sum if tool_available_sum else 0.0
            )
            retrieval_hit_rate = (retrieval_hit / retrieval_total) if retrieval_total else 0.0
            tool_success_rate = (
                (tool_result_total - tool_result_failed) / tool_result_total if tool_result_total else 1.0
            )
            proactive_total_blocks = sum(proactive_block_reasons.values())
            top_block_reasons = dict(
                sorted(proactive_block_reasons.items(), key=lambda kv: kv[1], reverse=True)[:5]
            )

            return {
                "retrieval": {
                    "total": retrieval_total,
                    "hit": retrieval_hit,
                    "hit_rate": round(retrieval_hit_rate, 4),
                    "miss": max(0, retrieval_total - retrieval_hit),
                },
                "tool_selection": {
                    "total": tool_selection_total,
                    "avg_selected": round(tool_selection_avg, 2),
                    "coverage": round(tool_selection_coverage, 4),
                    "tool_success_rate": round(tool_success_rate, 4),
                    "tool_failures": tool_result_failed,
                },
                "proactive": {
                    "sent": proactive_sent,
                    "blocked_total": proactive_total_blocks,
                    "top_block_reasons": top_block_reasons,
                },
            }

        session_quality: dict[str, dict[str, Any]] = {}
        for event in all_events:
            session_id = str(event.get("session_id") or "").strip()
            if not session_id:
                continue
            row = session_quality.setdefault(
                session_id,
                {
                    "retrieval_total": 0,
                    "retrieval_hit": 0,
                    "proactive_sent": 0,
                    "proactive_blocked": 0,
                },
            )
            event_type = str(event.get("type") or "")
            if event_type == "retrieval":
                row["retrieval_total"] += 1
                if int(event.get("items") or 0) > 0:
                    row["retrieval_hit"] += 1
            elif event_type == "proactive_sent":
                row["proactive_sent"] += 1
            elif event_type in {"proactive_judge", "proactive_decision", "proactive_tick_skipped"}:
                row["proactive_blocked"] += 1

        for row in session_quality.values():
            total = int(row["retrieval_total"])
            hit = int(row["retrieval_hit"])
            row["retrieval_hit_rate"] = round((hit / total), 4) if total else 0.0

        base = _aggregate(all_events)
        base["window_1h"] = _aggregate(events_1h)
        base["window_24h"] = _aggregate(events_24h)
        base["by_session"] = session_quality
        return base

    def _get(self, name: str) -> RuntimeUnit:
        unit = self.units.get(name)
        if unit is None:
            raise ValueError(f"unknown runtime unit: {name}")
        return unit
