from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExtensionRecord:
    kind: str
    name: str
    version: str
    enabled: bool
    compatibility: str
    source: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)
