from dataclasses import dataclass

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
    ) -> None:
        self.scorer = scorer or ContextScorer()
        self.quality_checker = quality_checker or MessageQualityChecker()
        self.min_relevance = min_relevance
        self.min_interruptibility = min_interruptibility

    def decide(self, candidate: ProactiveCandidate) -> JudgeDecision:
        ok, reason = self.quality_checker.check(candidate.content)
        if not ok:
            return JudgeDecision(action="skip", reason=f"quality_{reason}")
        score = self.scorer.score(candidate)
        if score.relevance < self.min_relevance:
            return JudgeDecision(action="defer", reason="low_relevance")
        if score.interruptibility < self.min_interruptibility:
            return JudgeDecision(action="defer", reason="low_interruptibility")
        return JudgeDecision(action="send", reason="score_ok")

