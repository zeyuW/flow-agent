from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from flow_agent.marketplace.models import ExtensionRecord


@dataclass(slots=True)
class MarketplaceIndex:
    path: Path

    def load(self) -> list[ExtensionRecord]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        rows: list[ExtensionRecord] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            rows.append(
                ExtensionRecord(
                    kind=str(item.get("kind") or ""),
                    name=str(item.get("name") or ""),
                    version=str(item.get("version") or "0.0.0"),
                    enabled=bool(item.get("enabled", True)),
                    compatibility=str(item.get("compatibility") or ">=1.0.0"),
                    source=str(item.get("source") or "local"),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return rows

    def save(self, rows: list[ExtensionRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
