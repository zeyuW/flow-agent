from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeHealth:
    name: str
    ok: bool
    detail: str = ""
    status: str = "healthy"
    restart_policy: str = "manual"


@dataclass(slots=True)
class RuntimeUnitSnapshot:
    name: str
    running: bool
    details: dict[str, Any] = field(default_factory=dict)
    health: str = "unknown"
    restart_policy: str = "manual"


@dataclass(slots=True)
class RuntimeServiceSnapshot:
    runtimes: list[RuntimeUnitSnapshot]
    metrics: dict[str, Any]
    event_summary: dict[str, Any]
