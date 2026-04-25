from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class APIKeyAuth:
    expected_key: str | None = None

    def verify(self, provided_key: str | None) -> bool:
        if not self.expected_key:
            return True
        return bool(provided_key) and provided_key == self.expected_key
