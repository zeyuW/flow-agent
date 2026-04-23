import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class BaselineStore:
    """Baseline storage with simple JSON persistence."""

    path: Path

    def load(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

