import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from flow_agent.background.jobs import JobSpec
from flow_agent.background.store import JobRun
from flow_agent.background.writer import JobStoreWriter
from flow_agent.runtime.errors import classify_error


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
    _running_jobs: set[str] = field(default_factory=set)
    _running_jobs_lock: threading.Lock = field(default_factory=threading.Lock)
    _pending_async: int = 0
    _pending_lock: threading.Lock = field(default_factory=threading.Lock)
    _threads: set[threading.Thread] = field(default_factory=set)
    _threads_lock: threading.Lock = field(default_factory=threading.Lock)
    _writer: JobStoreWriter | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """为可持久化存储创建唯一写入者。"""

        if hasattr(self.store, "start_run"):
            self._writer = JobStoreWriter(self.store)

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
        elif self._writer is not None:
            self._writer.close()
        elif hasattr(self.store, "close"):
            self.store.close()

    def run_job(self, job_name: str) -> JobRun:
        """同步执行任务，并记录重试和终态。"""

        job = self.registry.get(job_name)
        if job is None:
            raise ValueError(f"unknown job: {job_name}")
        with self._running_jobs_lock:
            if job_name in self._running_jobs:
                raise RuntimeError("background job already running")
            self._running_jobs.add(job_name)
        if hasattr(self.store, "start_run"):
            run = self._write(lambda: self.store.start_run(job_name))
        else:
            run = JobRun(job_name=job_name, ok=False, attempts=0, status="running")
            self._write(lambda: self.store.append(run))
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
                    run.error_category = None
                    break
                except Exception as exc:
                    run.ok = False
                    error_info = classify_error(exc)
                    run.error = error_info.message
                    run.error_category = error_info.category.value
                    if attempts < max_attempts:
                        run.status = "retrying"
                        self._write(lambda: self.store.append(run))
                    else:
                        run.status = "failed"
                    if attempts >= max_attempts:
                        logger.exception(
                            "后台任务失败: name=%s attempts=%s",
                            job_name,
                            attempts,
                        )
            return run
        finally:
            run.finished_at = run.finished_at or _utc_now()
            self._write(lambda: self.store.append(run))
            self._record(
                {
                    "type": "job_end",
                    "job": job_name,
                    "ok": run.ok,
                    "attempts": run.attempts,
                    "error": run.error,
                }
            )
            with self._running_jobs_lock:
                self._running_jobs.discard(job_name)

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

    def _write(self, action):
        """通过唯一写入者执行存储操作。"""

        if self._writer is not None:
            return self._writer.call(action)
        return action()


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
