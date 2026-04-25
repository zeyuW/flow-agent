from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class IncidentStore:
    _items: list[dict[str, Any]] = field(default_factory=list)

    def report(self, kind: str, detail: str, metadata: dict[str, Any] | None = None) -> None:
        self._items.append(
            {
                "timestamp": _now_iso(),
                "kind": kind,
                "detail": detail,
                "metadata": metadata or {},
            }
        )

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._items[-max(1, limit):]
