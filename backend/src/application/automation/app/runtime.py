"""自动化作业运行时：注册、排队、触发和生命周期编排。"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

from application.automation.app.executor import AutomationExecutor
from application.automation.domain.models import JobRun, JobSpec
from application.automation.infra.writer import JobStoreWriter

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _QueuedJobRequest:
    """保留排队任务的取消状态，避免从线程安全队列中删除元素。"""

    job_name: str
    cancelled: bool = False


class AutomationRegistry:
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

    def list_jobs(self) -> list[JobSpec]:
        """返回当前任务快照，供触发器遍历。"""

        with self._lock:
            return list(self._jobs.values())


@dataclass(slots=True)
class AutomationRuntime:
    """统一管理异步队列、事件触发、周期触发和运行时生命周期。"""

    registry: AutomationRegistry
    store: object
    scheduler: object | None = None
    config_watcher: object | None = None
    event_bus: object | None = None
    max_async_queue: int = 64
    max_async_workers: int = 4
    shutdown_timeout_seconds: float = 5.0
    trace_recorder: object | None = None
    _queued_jobs: set[str] = field(default_factory=set)
    _queued_jobs_lock: threading.Lock = field(default_factory=threading.Lock)
    _queued_requests: dict[str, list[_QueuedJobRequest]] = field(default_factory=dict)
    _execution_queue: queue.Queue[_QueuedJobRequest | None] = field(init=False)
    _workers: list[threading.Thread] = field(default_factory=list)
    _workers_lock: threading.Lock = field(default_factory=threading.Lock)
    _interval_thread: threading.Thread | None = field(default=None, init=False)
    _interval_stop: threading.Event = field(default_factory=threading.Event)
    _started: bool = field(default=False, init=False)
    _started_lock: threading.Lock = field(default_factory=threading.Lock)
    _writer: JobStoreWriter | None = field(default=None, init=False)
    _executor: AutomationExecutor = field(init=False)

    def __post_init__(self) -> None:
        """初始化执行器、队列和可选的串行存储写入者。"""

        if hasattr(self.store, "start_run"):
            self._writer = JobStoreWriter(self.store)
        self._execution_queue = queue.Queue(maxsize=max(1, self.max_async_queue))
        self._executor = AutomationExecutor(
            registry=self.registry,
            store=self.store,
            writer=self._writer,
            trace_recorder=self.trace_recorder,
        )

    def start(self) -> None:
        """启动后台作业的 worker、事件触发和周期触发。"""

        with self._started_lock:
            if self._started:
                return
            self._started = True
        self._start_workers()
        self._bind_event_triggers()
        self._start_interval_loop()
        if self.scheduler is not None:
            self.scheduler.start()
        if self.config_watcher is not None:
            self.config_watcher.start()

    def stop(self) -> None:
        """停止触发器、worker 和存储写入者。"""

        self._unbind_event_triggers()
        self._interval_stop.set()
        if self._interval_thread is not None:
            self._interval_thread.join(timeout=max(0.1, self.shutdown_timeout_seconds))
            self._interval_thread = None
        if self.scheduler is not None:
            self.scheduler.stop()
        if self.config_watcher is not None:
            self.config_watcher.stop()
        with self._workers_lock:
            workers = list(self._workers)
        for _ in workers:
            self._execution_queue.put(None)
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(timeout=max(0.1, self.shutdown_timeout_seconds))
        alive = [worker.name for worker in workers if worker.is_alive()]
        if alive:
            logger.warning("后台任务停止超时，保留状态连接等待进程退出: %s", alive)
        elif self._writer is not None:
            self._writer.close()
        elif hasattr(self.store, "close"):
            self.store.close()
        with self._started_lock:
            self._started = False

    def run_job(self, job_name: str) -> JobRun:
        """委托执行器同步运行一个作业。"""

        return self._executor.run_job(job_name)

    def run_job_async(self, job_name: str) -> bool:
        """将任务提交到有界 worker 队列；合并时返回 False。"""

        job = self.registry.get(job_name)
        if job is None:
            raise ValueError(f"unknown job: {job_name}")
        self._start_workers()
        if self._executor.is_debounced(job):
            return False
        with self._queued_jobs_lock:
            if job.coalesce and job_name in self._queued_jobs:
                return False
            try:
                request = _QueuedJobRequest(job_name=job_name)
                self._execution_queue.put_nowait(request)
            except queue.Full as error:
                raise RuntimeError("background_async_queue_full") from error
            if job.coalesce:
                self._queued_jobs.add(job_name)
            self._queued_requests.setdefault(job_name, []).append(request)
            pending = self._execution_queue.qsize()
        self._record(
            {
                "type": "background_job_queued",
                "job": job_name,
                "attempts": 0,
                "status": "queued",
                "pending": pending,
            }
        )
        return True

    def cancel_queued_job(self, job_name: str) -> int:
        """标记尚未开始执行的任务，不影响已经开始的同步任务。"""

        with self._queued_jobs_lock:
            requests = self._queued_requests.pop(job_name, [])
            cancelled = [request for request in requests if not request.cancelled]
            for request in cancelled:
                request.cancelled = True
            if cancelled:
                self._queued_jobs.discard(job_name)
        for _ in cancelled:
            self._record(
                {
                    "type": "background_job_cancelled",
                    "job": job_name,
                    "attempts": 0,
                    "status": "cancelled",
                }
            )
        return len(cancelled)

    def on_event(self, event: object) -> None:
        """接收生命周期事件，并提交精确匹配的声明式任务。"""

        for job in self.registry.list_jobs():
            if job.event_type is not None and type(event) is job.event_type:
                try:
                    self.run_job_async(job.name)
                except Exception:
                    logger.exception("事件触发后台任务失败: job=%s", job.name)

    def _start_workers(self) -> None:
        with self._workers_lock:
            alive = [worker for worker in self._workers if worker.is_alive()]
            if alive:
                self._workers = alive
                return
            self._workers = []
            for index in range(max(1, self.max_async_workers)):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"background-worker:{index + 1}",
                    daemon=True,
                )
                self._workers.append(worker)
                worker.start()

    def _worker_loop(self) -> None:
        while True:
            request = self._execution_queue.get()
            try:
                if request is None:
                    return
                with self._queued_jobs_lock:
                    requests = self._queued_requests.get(request.job_name, [])
                    if request in requests:
                        requests.remove(request)
                    if not requests:
                        self._queued_requests.pop(request.job_name, None)
                if not request.cancelled:
                    self.run_job(request.job_name)
            except Exception:
                logger.exception(
                    "后台任务执行失败: name=%s",
                    request.job_name if request is not None else "stop",
                )
            finally:
                if request is not None:
                    with self._queued_jobs_lock:
                        self._queued_jobs.discard(request.job_name)
                self._execution_queue.task_done()

    def _bind_event_triggers(self) -> None:
        if self.event_bus is not None:
            self.event_bus.subscribe(self)

    def _unbind_event_triggers(self) -> None:
        if self.event_bus is not None:
            self.event_bus.unsubscribe(self)

    def _start_interval_loop(self) -> None:
        self._interval_stop.clear()
        self._interval_thread = threading.Thread(
            target=self._interval_loop,
            name="background-job-intervals",
            daemon=True,
        )
        self._interval_thread.start()

    def _interval_loop(self) -> None:
        next_due: dict[str, float] = {}
        while not self._interval_stop.is_set():
            now = time.monotonic()
            active: set[str] = set()
            for job in self.registry.list_jobs():
                if job.interval_seconds is None:
                    continue
                interval = max(0.01, float(job.interval_seconds))
                active.add(job.name)
                due = next_due.setdefault(job.name, now + interval)
                if now >= due:
                    try:
                        self.run_job_async(job.name)
                    except Exception:
                        logger.exception("间隔触发后台任务失败: job=%s", job.name)
                    next_due[job.name] = now + interval
            for name in set(next_due) - active:
                del next_due[name]
            self._interval_stop.wait(0.01)

    def _record(self, event: dict[str, object]) -> None:
        if self.trace_recorder is None:
            return
        try:
            self.trace_recorder.record(dict(event))
        except Exception:
            logger.exception("后台任务观测记录失败")
