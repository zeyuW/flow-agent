from dataclasses import dataclass
from datetime import datetime, timezone

from flow_agent.proactive.context_scoring import ContextScorer
from flow_agent.proactive.message_quality import MessageQualityChecker
from flow_agent.proactive.types import ProactiveCandidate


@dataclass(slots=True)
class JudgeDecision:
    action: str  # send|defer|skip
    reason: str


class ProactiveJudge:
    """Hybrid rule-based proactive judge."""

    def __init__(
        self,
        scorer: ContextScorer | None = None,
        quality_checker: MessageQualityChecker | None = None,
        min_relevance: float = 0.45,
        min_interruptibility: float = 0.55,
        min_effective_priority: float = 0.55,
        active_hours: tuple[int, int] = (8, 22),
        max_energy: float = 1.0,
        recover_per_tick: float = 0.1,
    ) -> None:
        self.scorer = scorer or ContextScorer()
        self.quality_checker = quality_checker or MessageQualityChecker()
        self.min_relevance = min_relevance
        self.min_interruptibility = min_interruptibility
        self.min_effective_priority = min_effective_priority
        self.active_hours = active_hours
        self.max_energy = max(0.2, max_energy)
        self.recover_per_tick = max(0.0, recover_per_tick)
        self._energy = self.max_energy

    def decide(self, candidate: ProactiveCandidate) -> JudgeDecision:
        self._energy = min(self.max_energy, self._energy + self.recover_per_tick)
        hour = datetime.now(timezone.utc).hour
        if not (self.active_hours[0] <= hour < self.active_hours[1]):
            return JudgeDecision(action="defer", reason="quiet_hours")
        ok, reason = self.quality_checker.check(candidate.content)
        if not ok:
            return JudgeDecision(action="skip", reason=f"quality_{reason}")
        score = self.scorer.score(candidate)
        effective_priority = (candidate.priority + score.relevance + score.interruptibility) / 3.0
        if effective_priority < self.min_effective_priority:
            return JudgeDecision(action="defer", reason="low_effective_priority")
        if score.relevance < self.min_relevance:
            return JudgeDecision(action="defer", reason="low_relevance")
        if score.interruptibility < self.min_interruptibility:
            return JudgeDecision(action="defer", reason="low_interruptibility")
        if self._energy < 0.25:
            return JudgeDecision(action="defer", reason="low_energy")
        self._energy = max(0.0, self._energy - 0.25)
        return JudgeDecision(action="send", reason="score_ok")

