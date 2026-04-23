from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class EventEnvelope:
    event_type: str
    payload: dict[str, Any]
    timestamp: str
    correlation_id: str
    parent_id: str | None
    session_id: str | None
    trace_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.event_type,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "parent_id": self.parent_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            **self.payload,
        }


def to_envelope(event: dict[str, Any]) -> EventEnvelope:
    event_type = str(event.get("type") or "unknown")
    payload = {k: v for k, v in event.items() if k not in _RESERVED}
    return EventEnvelope(
        event_type=event_type,
        payload=payload,
        timestamp=str(event.get("timestamp") or utc_now_iso()),
        correlation_id=str(event.get("correlation_id") or uuid4().hex[:12]),
        parent_id=_optional_str(event.get("parent_id")),
        session_id=_optional_str(event.get("session_id")),
        trace_id=_optional_str(event.get("trace_id")),
    )


def classify_event(event_type: str) -> str:
    if event_type.startswith("turn_") or event_type in {"retrieval", "memory_organize", "delegation_decision"}:
        return "turn"
    if event_type.startswith("tool_"):
        return "tool"
    if event_type.startswith("proactive_"):
        return "proactive"
    if event_type.startswith("subagent_"):
        return "subagent"
    if event_type.startswith("job_"):
        return "job"
    return "turn"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_RESERVED = {
    "type",
    "timestamp",
    "correlation_id",
    "parent_id",
    "session_id",
    "trace_id",
}
