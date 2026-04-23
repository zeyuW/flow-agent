import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DashboardSnapshot:
    turns: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    proactive: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    subagents: list[dict[str, Any]]


class InMemoryDashboardStore:
    """A lightweight, in-memory store for recent runtime events."""

    def __init__(self, capacity: int = 200) -> None:
        self.capacity = max(10, capacity)
        self._lock = threading.Lock()
        self._turns: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._tools: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._proactive: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._jobs: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._subagents: deque[dict[str, Any]] = deque(maxlen=self.capacity)

    def record(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        with self._lock:
            if event_type.startswith("turn_") or event_type in {"retrieval"}:
                self._turns.append(event)
            elif event_type.startswith("tool_"):
                self._tools.append(event)
            elif event_type.startswith("proactive_"):
                self._proactive.append(event)
            elif event_type.startswith("job_"):
                self._jobs.append(event)
            elif event_type.startswith("subagent_"):
                self._subagents.append(event)
            else:
                # Keep unknown events in turns for visibility.
                self._turns.append(event)

    def snapshot(self) -> DashboardSnapshot:
        with self._lock:
            return DashboardSnapshot(
                turns=list(self._turns),
                tools=list(self._tools),
                proactive=list(self._proactive),
                jobs=list(self._jobs),
                subagents=list(self._subagents),
            )

