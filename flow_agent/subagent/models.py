from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class SubagentTask:
    """A delegatable task executed by a subagent runtime."""

    task_id: str
    kind: str
    payload: dict[str, object]
    status: str = "created"  # created | running | completed | failed
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, object] | None = None
    error: str | None = None

