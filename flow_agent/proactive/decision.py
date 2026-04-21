from dataclasses import dataclass

from flow_agent.proactive.models import ProactiveCandidate


@dataclass(slots=True)
class Decision:
    action: str  # send | skip | defer
    reason: str


class DecisionLayer:
    def __init__(self, min_priority_to_send: float = 0.5) -> None:
        self.min_priority_to_send = min_priority_to_send

    def decide(self, candidate: ProactiveCandidate) -> Decision:
        if candidate.priority >= self.min_priority_to_send:
            return Decision(action="send", reason="priority_ok")
        return Decision(action="defer", reason="low_priority")
