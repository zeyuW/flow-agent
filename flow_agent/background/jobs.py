from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(slots=True)
class JobSpec:
    """Job metadata and execution function."""

    name: str
    func: Callable[[], None]
    max_retries: int = 0


class JobRegistry(Protocol):
    def register(self, job: JobSpec) -> None:
        ...

    def get(self, name: str) -> JobSpec | None:
        ...

