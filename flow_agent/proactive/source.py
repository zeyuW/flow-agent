from pathlib import Path
from typing import Protocol

from flow_agent.proactive.models import ProactiveCandidate


class ProactiveSource(Protocol):
    def fetch_candidates(self) -> list[ProactiveCandidate]:
        ...


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
            candidates.append(
                ProactiveCandidate(
                    key=key,
                    content=content,
                    source="file_feed",
                    priority=0.4,
                )
            )
        return candidates


class LocalTodoCandidateSource:
    def __init__(self, todo_file: Path) -> None:
        self.todo_file = todo_file

    def fetch_candidates(self) -> list[ProactiveCandidate]:
        if not self.todo_file.exists():
            return []
        candidates: list[ProactiveCandidate] = []
        for line in self.todo_file.read_text(encoding="utf-8").splitlines():
            content = line.strip()
            if not content or content.startswith("#"):
                continue
            key = f"todo:{content.lower()}"
            candidates.append(
                ProactiveCandidate(
                    key=key,
                    content=f"[TODO] {content}",
                    source="local_todo",
                    priority=0.9,
                )
            )
        return candidates
