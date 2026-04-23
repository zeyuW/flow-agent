import logging
import threading
from dataclasses import dataclass, field

from flow_agent.background.jobs import JobSpec
from flow_agent.background.store import InMemoryJobStore, JobRun
from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.guard.guards import BackgroundReentryGuard
from flow_agent.runtime.retry import RetryPolicy, retry_call


logger = logging.getLogger(__name__)


class InMemoryJobRegistry:
    """Simple job registry."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobSpec] = {}

    def register(self, job: JobSpec) -> None:
        self._jobs[job.name] = job

    def get(self, name: str) -> JobSpec | None:
        return self._jobs.get(name)


@dataclass(slots=True)
class BackgroundRuntime:
    """Manage async/delayed/periodic jobs in a single place."""

    registry: InMemoryJobRegistry
    store: InMemoryJobStore
    dashboard: InMemoryDashboardStore | None = None
    max_async_queue: int = 64
    _lock: threading.Lock = field(default_factory=threading.Lock)
    reentry_guard: BackgroundReentryGuard = field(default_factory=BackgroundReentryGuard)
    _pending_async: int = 0
    _pending_lock: threading.Lock = field(default_factory=threading.Lock)

    def run_job(self, job_name: str) -> JobRun:
        """Run a job synchronously with retry and trace."""

        job = self.registry.get(job_name)
        if job is None:
            raise ValueError(f"unknown job: {job_name}")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("background runtime busy")
        guard_decision = self.reentry_guard.acquire()
        if not guard_decision.allowed:
            self._lock.release()
            raise RuntimeError(guard_decision.reason)
        run = JobRun(job_name=job_name, ok=False, attempts=0)
        self._record({"type": "job_start", "job": job_name})
        try:
            attempts = 0
            while True:
                attempts += 1
                run.attempts = attempts
                try:
                    retry_call(
                        job.func,
                        policy=RetryPolicy(max_attempts=max(1, job.max_retries + 1)),
                    )
                    run.ok = True
                    run.error = None
                    break
                except Exception as exc:
                    run.ok = False
                    run.error = str(exc)
                    logger.exception("job failed name=%s attempt=%s", job_name, attempts)
                    break
            return run
        finally:
            run.finished_at = run.finished_at or _utc_now()
            self.store.append(run)
            self._record(
                {
                    "type": "job_end",
                    "job": job_name,
                    "ok": run.ok,
                    "attempts": run.attempts,
                    "error": run.error,
                }
            )
            self.reentry_guard.release()
            self._lock.release()

    def run_job_async(self, job_name: str) -> None:
        with self._pending_lock:
            if self._pending_async >= max(1, self.max_async_queue):
                raise RuntimeError("background_async_queue_full")
            self._pending_async += 1
        self._record({"type": "job_queue", "job": job_name, "pending": self._pending_async})

        def _run() -> None:
            try:
                self.run_job(job_name)
            finally:
                with self._pending_lock:
                    self._pending_async = max(0, self._pending_async - 1)

        threading.Thread(target=_run, daemon=True).start()

    def _record(self, event: dict[str, object]) -> None:
        if self.dashboard is None:
            return
        try:
            self.dashboard.record(event)
        except Exception:
            logger.exception("dashboard record job event failed")


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)

