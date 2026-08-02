from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

from infra.observability.events import classify_event, to_envelope


@dataclass(slots=True)
class UnifiedEventSnapshot:
    turns: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    proactive: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    subagents: list[dict[str, Any]]
    all_events: list[dict[str, Any]]


class UnifiedEventStore:
    """Unified event store with envelope normalization."""

    def __init__(self, capacity: int = 300) -> None:
        self.capacity = max(20, capacity)
        self._lock = threading.Lock()
        self._turns: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._tools: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._proactive: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._jobs: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._subagents: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._all: deque[dict[str, Any]] = deque(maxlen=self.capacity * 3)

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        normalized = to_envelope(event).to_dict()
        bucket = classify_event(str(normalized.get("type") or ""))
        with self._lock:
            self._all.append(normalized)
            if bucket == "turn":
                self._turns.append(normalized)
            elif bucket == "tool":
                self._tools.append(normalized)
            elif bucket == "proactive":
                self._proactive.append(normalized)
            elif bucket == "job":
                self._jobs.append(normalized)
            elif bucket == "subagent":
                self._subagents.append(normalized)
        return normalized

    def snapshot(self) -> UnifiedEventSnapshot:
        with self._lock:
            return UnifiedEventSnapshot(
                turns=list(self._turns),
                tools=list(self._tools),
                proactive=list(self._proactive),
                jobs=list(self._jobs),
                subagents=list(self._subagents),
                all_events=list(self._all),
            )
