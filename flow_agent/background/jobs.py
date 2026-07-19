from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(slots=True)
class JobSpec:
    """后台任务元数据和执行函数。"""

    name: str
    func: Callable[[], Any]
    max_retries: int = 0


class JobRegistry(Protocol):
    def register(self, job: JobSpec) -> None:
        ...

    def get(self, name: str) -> JobSpec | None:
        ...

    def unregister(self, name: str) -> None:
        ...
