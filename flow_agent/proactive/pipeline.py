import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

from flow_agent.infra.trace import TraceRecorder
from flow_agent.guard.guards import ProactiveFrequencyGuard, SourceIsolationGuard
from flow_agent.proactive.judge import ProactiveJudge
from flow_agent.proactive.dispatcher import ProactiveDispatcher
from flow_agent.proactive.sources import ProactiveSource, record_to_candidate
from flow_agent.proactive.store import ProactiveSentStore
from flow_agent.proactive.types import (
    ProactiveCandidate,
    ProactiveGateDecision,
    ProactiveTickResult,
    SourceRecord,
)
from flow_agent.skills.registry import SkillRegistry


logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContentStore:
    """Store normalized source records and filter duplicates by dedup key."""

    def __init__(self) -> None:
        self._records_by_key: dict[str, SourceRecord] = {}

    def ingest(self, records: Iterable[SourceRecord]) -> list[SourceRecord]:
        new_records: list[SourceRecord] = []
        for record in records:
            if record.dedup_key in self._records_by_key:
                continue
            self._records_by_key[record.dedup_key] = record
            new_records.append(record)
        logger.debug("content store ingested %s new records", len(new_records))
        return new_records


class PreGate:
    """预检冷却时间并返回门决策。"""

    def __init__(self, sent_store: ProactiveSentStore, cooldown_seconds: int) -> None:
        self.sent_store = sent_store
        self.cooldown_seconds = cooldown_seconds

    def check(self) -> ProactiveGateDecision:
        last_sent_at = self.sent_store.get_last_sent_at()
        if last_sent_at is None:
            return ProactiveGateDecision(allowed=True, reason="ok")
        if _utc_now() - last_sent_at < timedelta(seconds=self.cooldown_seconds):
            return ProactiveGateDecision(allowed=False, reason="cooldown")
        return ProactiveGateDecision(allowed=True, reason="ok")


class SourceGateway:
    """Aggregate records from all sources with source-level failure isolation."""

    def __init__(self, sources: list[ProactiveSource]) -> None:
        self.sources = sources

    def fetch_records(self) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for source in self.sources:
            source_check = SourceIsolationGuard.check_source_name(source.name)
            if not source_check.allowed:
                logger.warning("source blocked by guard: %s", source_check.reason)
                continue
            try:
                records.extend(source.fetch_records())
            except Exception:
                logger.exception("source fetch failed: %s", source.name)
        return records


class CandidateRanker:
    """Sort candidates by priority and stable key."""

    def rank(self, candidates: list[ProactiveCandidate]) -> list[ProactiveCandidate]:
        return sorted(candidates, key=lambda c: (-c.priority, c.key))


@dataclass(slots=True)
class Decision:
    action: str  # send | skip | defer
    reason: str


class DecisionLayer:
    """Simple decision rule based on min priority."""

    def __init__(self, min_priority_to_send: float = 0.5) -> None:
        self.min_priority_to_send = min_priority_to_send

    def decide(self, candidate: ProactiveCandidate) -> Decision:
        if candidate.priority >= self.min_priority_to_send:
            return Decision(action="send", reason="priority_ok")
        return Decision(action="defer", reason="low_priority")


class DriftRunner:
    '''运行轻量级漂移任务，可选技能驱动选择。'''

    def __init__(
        self,
        tasks_file: Path,
        skill_registry: SkillRegistry | None = None,
        available_tools: set[str] | None = None,
        available_sources: set[str] | None = None,
        available_mcp: set[str] | None = None,
    ) -> None:
        self.tasks_file = tasks_file
        self.skill_registry = skill_registry
        self.available_tools = available_tools or set()
        self.available_sources = available_sources or set()
        self.available_mcp = available_mcp or set()

    def run(self) -> str:
        if self.skill_registry is not None:
            selected = self.skill_registry.select(
                available_tools=self.available_tools,
                available_sources=self.available_sources,
                available_mcp=self.available_mcp,
            )
            if selected is not None:
                return f"skill:{selected.name}"
        if not self.tasks_file.exists():
            return "no_task"
        for line in self.tasks_file.read_text(encoding="utf-8").splitlines():
            task = line.strip()
            if task and not task.startswith("#"):
                return f"selected:{task}"
        return "no_task"


@dataclass(slots=True)
class ProactiveTickRunner:
    '''主动运行时'''
    gate: PreGate
    gateway: SourceGateway
    ranker: CandidateRanker
    decision_layer: DecisionLayer
    drift_runner: DriftRunner
    sent_store: ProactiveSentStore
    dedup_ttl_seconds: int
    judge: ProactiveJudge | None = None
    content_store: ContentStore | None = None
    recorder: TraceRecorder | None = None
    frequency_guard: ProactiveFrequencyGuard | None = None
    dispatcher: ProactiveDispatcher | None = None

    def tick(self) -> ProactiveTickResult:
        started = time.perf_counter()
        if self.frequency_guard is not None:
            decision = self.frequency_guard.check()
            if not decision.allowed:
                self._trace("proactive_tick_skipped", {"reason": decision.reason})
                return ProactiveTickResult(sent=False, reason=decision.reason)
        gate = self.gate.check()
        if not gate.allowed:
            self._trace("proactive_tick_skipped", {"reason": gate.reason})
            return ProactiveTickResult(sent=False, reason=gate.reason)
        records = self.gateway.fetch_records()
        self._trace("proactive_source_fetch", {"count": len(records)})
        new_records = self.content_store.ingest(records) if self.content_store else records
        candidates = [record_to_candidate(record) for record in new_records]
        ranked = self.ranker.rank(candidates)
        candidate = ranked[0] if ranked else None
        if candidate is None:
            drift = self.drift_runner.run()
            self._trace("proactive_drift", {"result": drift})
            return ProactiveTickResult(sent=False, reason=f"no_candidate:{drift}")
        decision = self.decision_layer.decide(candidate)
        if decision.action != "send":
            self._trace(
                "proactive_decision",
                {"action": decision.action, "reason": decision.reason, "key": candidate.key},
            )
            return ProactiveTickResult(
                sent=False,
                reason=f"{decision.action}:{decision.reason}",
                candidate_key=candidate.key,
            )
        if self.judge is not None:
            judge_decision = self.judge.decide(candidate)
            if judge_decision.action != "send":
                self._trace(
                    "proactive_judge",
                    {
                        "action": judge_decision.action,
                        "reason": judge_decision.reason,
                        "key": candidate.key,
                    },
                )
                return ProactiveTickResult(
                    sent=False,
                    reason=f"{judge_decision.action}:{judge_decision.reason}",
                    candidate_key=candidate.key,
                )
        if self.sent_store.was_sent_recently(candidate.key, self.dedup_ttl_seconds):
            self._trace("proactive_dedup_hit", {"key": candidate.key})
            return ProactiveTickResult(sent=False, reason="dedup_hit", candidate_key=candidate.key)
        if self.dispatcher is not None:
            try:
                self.dispatcher.dispatch(candidate)
                self._trace(
                    "proactive_dispatch",
                    {"key": candidate.key, "target": "dispatcher"},
                )
            except Exception as exc:
                logger.exception("proactive dispatch failed key=%s", candidate.key)
                self._trace(
                    "proactive_dispatch_failed",
                    {"key": candidate.key, "error": str(exc)},
                )
                return ProactiveTickResult(
                    sent=False,
                    reason="dispatch_failed",
                    candidate_key=candidate.key,
                )
        self.sent_store.mark_sent(candidate.key)
        logger.info("proactive sent candidate key=%s", candidate.key)
        self._trace(
            "proactive_sent",
            {
                "key": candidate.key,
                "content": candidate.content,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return ProactiveTickResult(sent=True, reason="sent", candidate_key=candidate.key)

    def _trace(self, event_type: str, payload: dict[str, object]) -> None:
        if self.recorder is None:
            return
        self.recorder.record({"type": event_type, **payload})

