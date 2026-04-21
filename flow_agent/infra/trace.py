import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging


logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TraceRecorder:
    path: Path

    def record(self, event: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            enriched = {"ts": _utc_now_iso(), **event}
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(enriched, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("Failed to write trace event")
