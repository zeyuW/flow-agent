from dataclasses import dataclass

from flow_agent.proactive.types import ProactiveCandidate


@dataclass(slots=True)
class ContextScore:
    relevance: float
    interruptibility: float


class ContextScorer:
    """Score candidate context relevance and interruptibility."""

    def score(self, candidate: ProactiveCandidate) -> ContextScore:
        relevance = min(1.0, max(0.0, candidate.priority))
        # simple heuristic: todo/follow-up is less interruptive than generic long text
        interruptibility = 0.7
        if "TODO" in candidate.content or "Follow-up" in candidate.content:
            interruptibility = 0.9
        if len(candidate.content) > 180:
            interruptibility = 0.5
        return ContextScore(relevance=relevance, interruptibility=interruptibility)

