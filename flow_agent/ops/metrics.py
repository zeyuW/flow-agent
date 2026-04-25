from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(slots=True)
class MetricsStore:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _counters: dict[str, int] = field(default_factory=dict)

    def inc(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + max(0, amount)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)
