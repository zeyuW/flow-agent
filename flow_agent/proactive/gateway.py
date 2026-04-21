from flow_agent.proactive.models import ProactiveCandidate
from flow_agent.proactive.source import ProactiveSource


class SourceGateway:
    def __init__(self, sources: list[ProactiveSource]) -> None:
        self.sources = sources

    def fetch_candidates(self) -> list[ProactiveCandidate]:
        candidates: list[ProactiveCandidate] = []
        for source in self.sources:
            candidates.extend(source.fetch_candidates())
        return candidates
