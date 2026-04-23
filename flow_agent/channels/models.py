from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class InboundMessage:
    """A message received from an external channel."""

    channel: str
    session_id: str
    text: str
    received_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class OutboundMessage:
    """A message sent to an external channel."""

    channel: str
    session_id: str
    text: str
    sent_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, object] = field(default_factory=dict)

