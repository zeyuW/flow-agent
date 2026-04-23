import logging
import threading
import time
from dataclasses import dataclass

from flow_agent.background.jobs import JobSpec
from flow_agent.background.store import InMemoryJobStore, JobRun
from flow_agent.dashboard.store import InMemoryDashboardStore


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
    _lock: threading.Lock = threading.Lock()

    def run_job(self, job_name: str) -> JobRun:
        """Run a job synchronously with retry and trace."""

        job = self.registry.get(job_name)
        if job is None:
            raise ValueError(f"unknown job: {job_name}")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("background runtime busy")
        run = JobRun(job_name=job_name, ok=False, attempts=0)
        self._record({"type": "job_start", "job": job_name})
        try:
            attempts = 0
            while True:
                attempts += 1
                run.attempts = attempts
                try:
                    job.func()
                    run.ok = True
                    run.error = None
                    break
                except Exception as exc:
                    run.ok = False
                    run.error = str(exc)
                    logger.exception("job failed name=%s attempt=%s", job_name, attempts)
                    if attempts > job.max_retries:
                        break
                    time.sleep(0.05)
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
            self._lock.release()

    def run_job_async(self, job_name: str) -> None:
        threading.Thread(target=self.run_job, args=(job_name,), daemon=True).start()

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

