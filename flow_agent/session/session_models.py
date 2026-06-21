"""Session and message data models (spec 1c)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class SessionMeta:
    """Session row from SQLite sessions table."""

    key: str
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    last_consolidated: int = 0
    next_seq: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Session:
    """In-memory session object (spec 1c).

    Holds the full message list and metadata for a single conversation session.
    Supports history rebuild with start_index / max_messages and consolidation cursor.
    """

    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    last_consolidated: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
