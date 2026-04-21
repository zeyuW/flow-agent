import logging
from dataclasses import dataclass

from flow_agent.infra.trace import TraceRecorder
from flow_agent.proactive.decision import DecisionLayer
from flow_agent.proactive.drift import LocalDriftRunner
from flow_agent.proactive.gate import SimplePreGate
from flow_agent.proactive.gateway import SourceGateway
from flow_agent.proactive.models import ProactiveTickResult
from flow_agent.proactive.ranking import CandidateRanker
from flow_agent.proactive.store import ProactiveSentStore


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProactiveTickRunner:
    gate: SimplePreGate
    gateway: SourceGateway
    ranker: CandidateRanker
    decision_layer: DecisionLayer
    drift_runner: LocalDriftRunner
    sent_store: ProactiveSentStore
    dedup_ttl_seconds: int
    recorder: TraceRecorder | None = None

    def tick(self) -> ProactiveTickResult:
        gate = self.gate.check()
        if not gate.allowed:
            self._trace("proactive_tick_skipped", {"reason": gate.reason})
            return ProactiveTickResult(sent=False, reason=gate.reason)

        candidates = self.gateway.fetch_candidates()
        self._trace("proactive_source_fetch", {"count": len(candidates)})
        ranked = self.ranker.rank(candidates)
        candidate = self._select_candidate(ranked)
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

        if self.sent_store.was_sent_recently(candidate.key, self.dedup_ttl_seconds):
            self._trace("proactive_dedup_hit", {"key": candidate.key})
            return ProactiveTickResult(
                sent=False,
                reason="dedup_hit",
                candidate_key=candidate.key,
            )

        # Stage9最小版：这里只记录“会发送”，不接外部发送通道。
        self.sent_store.mark_sent(candidate.key)
        logger.info("proactive sent candidate key=%s", candidate.key)
        self._trace("proactive_sent", {"key": candidate.key, "content": candidate.content})
        return ProactiveTickResult(sent=True, reason="sent", candidate_key=candidate.key)

    def _select_candidate(
        self,
        candidates,
    ):
        return candidates[0] if candidates else None

    def _trace(self, event_type: str, payload: dict[str, object]) -> None:
        if self.recorder is None:
            return
        self.recorder.record({"type": event_type, **payload})
