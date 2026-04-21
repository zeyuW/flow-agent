from pathlib import Path

from flow_agent.proactive.models import ProactiveCandidate


class LocalFileCandidateSource:
    def __init__(self, source_file: Path) -> None:
        self.source_file = source_file

    def fetch_candidates(self) -> list[ProactiveCandidate]:
        if not self.source_file.exists():
            return []

        candidates: list[ProactiveCandidate] = []
        for line in self.source_file.read_text(encoding="utf-8").splitlines():
            content = line.strip()
            if not content or content.startswith("#"):
                continue
            key = content.lower()
            candidates.append(ProactiveCandidate(key=key, content=content))
        return candidates
