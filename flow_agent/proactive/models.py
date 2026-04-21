from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ProactiveCandidate:
    key: str
    content: str


@dataclass(slots=True)
class ProactiveGateDecision:
    allowed: bool
    reason: str


@dataclass(slots=True)
class ProactiveTickResult:
    sent: bool
    reason: str
    candidate_key: str | None = None


@dataclass(slots=True)
class SchedulerStatus:
    running: bool
    is_executing: bool
    last_started_at: datetime | None
    last_finished_at: datetime | None
