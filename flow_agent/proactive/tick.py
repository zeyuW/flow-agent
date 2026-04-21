import logging
from dataclasses import dataclass

from flow_agent.infra.trace import TraceRecorder
from flow_agent.proactive.gate import SimplePreGate
from flow_agent.proactive.models import ProactiveCandidate, ProactiveTickResult
from flow_agent.proactive.source import LocalFileCandidateSource
from flow_agent.proactive.store import ProactiveSentStore


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProactiveTickRunner:
    gate: SimplePreGate
    source: LocalFileCandidateSource
    sent_store: ProactiveSentStore
    dedup_ttl_seconds: int
    recorder: TraceRecorder | None = None

    def tick(self) -> ProactiveTickResult:
        gate = self.gate.check()
        if not gate.allowed:
            self._trace("proactive_tick_skipped", {"reason": gate.reason})
            return ProactiveTickResult(sent=False, reason=gate.reason)

        candidates = self.source.fetch_candidates()
        self._trace("proactive_source_fetch", {"count": len(candidates)})
        candidate = self._select_candidate(candidates)
        if candidate is None:
            return ProactiveTickResult(sent=False, reason="no_candidate")

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
        candidates: list[ProactiveCandidate],
    ) -> ProactiveCandidate | None:
        return candidates[0] if candidates else None

    def _trace(self, event_type: str, payload: dict[str, object]) -> None:
        if self.recorder is None:
            return
        self.recorder.record({"type": event_type, **payload})
