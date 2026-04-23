from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RegistryItem:
    name: str
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    health: str = "unknown"
