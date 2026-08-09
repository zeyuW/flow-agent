"""后台任务定义与运行记录。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class JobSpec:
    """自动化系统可注册、触发和执行的作业定义。"""

    name: str
    func: Callable[[], Any]
    max_retries: int = 0
    interval_seconds: float | None = None
    event_type: type[object] | None = None
    debounce_seconds: float = 0.0
    coalesce: bool = True
    retry_delay_seconds: float = 0.0
    retry_backoff_factor: float = 1.5


class JobRegistry(Protocol):
    """任务注册表的应用端口。"""

    def register(self, job: JobSpec) -> None: ...

    def get(self, name: str) -> JobSpec | None: ...

    def unregister(self, name: str) -> None: ...


@dataclass(slots=True)
class JobRun:
    """一次后台任务执行的领域记录。"""

    job_name: str
    ok: bool
    run_id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "running"
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    attempts: int = 1
    error: str | None = None
    error_category: str | None = None
    result: str | None = None
