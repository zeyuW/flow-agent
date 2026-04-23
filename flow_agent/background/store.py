import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class JobRun:
    job_name: str
    ok: bool
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    attempts: int = 1
    error: str | None = None


class InMemoryJobStore:
    """Keep recent job run history in memory."""

    def __init__(self, capacity: int = 200) -> None:
        self._lock = threading.Lock()
        self._runs: deque[JobRun] = deque(maxlen=max(10, capacity))

    def append(self, run: JobRun) -> None:
        with self._lock:
            self._runs.append(run)

    def list_runs(self) -> list[JobRun]:
        with self._lock:
            return list(self._runs)

