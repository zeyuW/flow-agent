from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PluginManifest:
    name: str
    description: str
    version: str
    compatibility: str = ">=1.0.0"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> "PluginManifest":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            name=str(raw.get("name") or path.parent.name),
            description=str(raw.get("description") or "no description"),
            version=str(raw.get("version") or "0.1.0"),
            compatibility=str(raw.get("compatibility") or ">=1.0.0"),
            enabled=bool(raw.get("enabled", True)),
            metadata=dict(raw.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "compatibility": self.compatibility,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }

    def write_to(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
