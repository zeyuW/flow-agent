import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from flow_agent.background.jobs import JobSpec
from flow_agent.background.store import JobRun
from flow_agent.guard.guards import BackgroundReentryGuard


logger = logging.getLogger(__name__)


class InMemoryJobRegistry:
    """进程内后台任务注册表。"""

    def __init__(self) -> None:
        self._jobs: dict[str, JobSpec] = {}
        self._lock = threading.RLock()

    def register(self, job: JobSpec) -> None:
        with self._lock:
            self._jobs[job.name] = job

    def unregister(self, name: str) -> None:
        with self._lock:
            self._jobs.pop(name, None)

    def get(self, name: str) -> JobSpec | None:
        with self._lock:
            return self._jobs.get(name)

    def list_names(self) -> list[str]:
        with self._lock:
            return sorted(self._jobs.keys())


@dataclass(slots=True)
class BackgroundRuntime:
    """统一管理同步、异步和调度触发的后台任务。"""

    registry: InMemoryJobRegistry
    store: Any
    scheduler: Any | None = None
    config_watcher: Any | None = None
    max_async_queue: int = 64
    shutdown_timeout_seconds: float = 5.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    reentry_guard: BackgroundReentryGuard = field(default_factory=BackgroundReentryGuard)
    _pending_async: int = 0
    _pending_lock: threading.Lock = field(default_factory=threading.Lock)
    _threads: set[threading.Thread] = field(default_factory=set)
    _threads_lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self) -> None:
        """启动已挂载的持久化调度服务。"""

        if self.scheduler is not None:
            self.scheduler.start()
        if self.config_watcher is not None:
            self.config_watcher.start()

    def stop(self) -> None:
        """停止已挂载的持久化调度服务。"""

        if self.scheduler is not None:
            self.scheduler.stop()
        if self.config_watcher is not None:
            self.config_watcher.stop()
        with self._threads_lock:
            threads = list(self._threads)
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=max(0.1, self.shutdown_timeout_seconds))
        alive = [thread.name for thread in threads if thread.is_alive()]
        if alive:
            logger.warning("后台任务停止超时，保留状态连接等待进程退出: %s", alive)
        elif hasattr(self.store, "close"):
            self.store.close()

    def run_job(self, job_name: str) -> JobRun:
        """同步执行任务，并记录重试和终态。"""

        job = self.registry.get(job_name)
        if job is None:
            raise ValueError(f"unknown job: {job_name}")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("background runtime busy")
        guard_decision = self.reentry_guard.acquire()
        if not guard_decision.allowed:
            self._lock.release()
            raise RuntimeError(guard_decision.reason)
        run = JobRun(job_name=job_name, ok=False, attempts=0, status="running")
        self.store.append(run)
        self._record({"type": "job_start", "job": job_name})
        try:
            attempts = 0
            max_attempts = max(1, job.max_retries + 1)
            while attempts < max_attempts:
                attempts += 1
                run.attempts = attempts
                try:
                    result = job.func()
                    run.ok = True
                    run.status = "succeeded"
                    run.result = "" if result is None else str(result)
                    run.error = None
                    break
                except Exception as exc:
                    run.ok = False
                    run.status = "failed"
                    run.error = str(exc)
                    if attempts >= max_attempts:
                        logger.exception(
                            "后台任务失败: name=%s attempts=%s",
                            job_name,
                            attempts,
                        )
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
                with self._threads_lock:
                    self._threads.discard(threading.current_thread())

        thread = threading.Thread(
            target=_run,
            name=f"background-job:{job_name}",
            daemon=True,
        )
        with self._threads_lock:
            self._threads.add(thread)
        thread.start()

    def _record(self, event: dict[str, object]) -> None:
        pass


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
