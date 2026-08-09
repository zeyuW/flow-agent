"""自动化作业的单次执行、重试和运行记录。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from application.automation.domain.models import JobRun, JobSpec
from application.automation.infra.writer import JobStoreWriter
from infra.resilience import RetryPolicy, classify_error, retry_call

logger = logging.getLogger(__name__)


class AutomationExecutor:
    """执行单个自动化作业，并维护作业级并发和防抖状态。"""

    def __init__(
        self,
        *,
        registry,
        store,
        writer: JobStoreWriter | None,
        trace_recorder=None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.writer = writer
        self.trace_recorder = trace_recorder
        self._running_jobs: set[str] = set()
        self._running_jobs_lock = threading.Lock()
        self._last_success_at: dict[str, datetime] = {}
        self._last_success_lock = threading.Lock()

    def run_job(self, job_name: str) -> JobRun:
        """同步执行作业，并记录重试过程和最终状态。"""

        job = self.registry.get(job_name)
        if job is None:
            raise ValueError(f"unknown job: {job_name}")
        with self._running_jobs_lock:
            if job.coalesce and job_name in self._running_jobs:
                raise RuntimeError("background job already running")
            if job.coalesce:
                self._running_jobs.add(job_name)

        if hasattr(self.store, "start_run"):
            run = self._write(lambda: self.store.start_run(job_name))
        else:
            run = JobRun(job_name=job_name, ok=False, attempts=0, status="running")
            self._write(lambda: self.store.append(run))
        self._record(
            {
                "type": "background_job_started",
                "job": job_name,
                "run_id": run.run_id,
                "attempts": 0,
                "status": run.status,
            }
        )

        try:
            attempts = 0

            def invoke() -> Any:
                nonlocal attempts
                attempts += 1
                run.attempts = attempts
                return job.func()

            def on_retry(error: Exception, attempt: int) -> None:
                error_info = classify_error(error)
                run.ok = False
                run.attempts = attempt
                run.status = "retrying"
                run.error = error_info.message
                run.error_category = error_info.category.value
                self._write(lambda: self.store.append(run))
                self._record(
                    {
                        "type": "background_job_retrying",
                        "job": job_name,
                        "run_id": run.run_id,
                        "attempts": attempt,
                        "status": run.status,
                        "error_category": run.error_category,
                    }
                )

            try:
                result = retry_call(
                    invoke,
                    policy=RetryPolicy(
                        max_attempts=max(1, job.max_retries + 1),
                        delay_seconds=max(0.0, job.retry_delay_seconds),
                        backoff_factor=max(1.0, job.retry_backoff_factor),
                        retryable_only=True,
                    ),
                    on_retry=on_retry,
                )
            except Exception as error:
                error_info = classify_error(error)
                run.ok = False
                run.status = "failed"
                run.error = error_info.message
                run.error_category = error_info.category.value
                logger.exception(
                    "后台任务失败: name=%s attempts=%s",
                    job_name,
                    attempts,
                )
            else:
                run.ok = True
                run.status = "succeeded"
                run.result = "" if result is None else str(result)
                run.error = None
                run.error_category = None
                with self._last_success_lock:
                    self._last_success_at[job_name] = _utc_now()
            return run
        finally:
            run.finished_at = run.finished_at or _utc_now()
            self._write(lambda: self.store.append(run))
            self._record(
                {
                    "type": "background_job_finished",
                    "job": job_name,
                    "run_id": run.run_id,
                    "attempts": run.attempts,
                    "status": run.status,
                    "error_category": run.error_category,
                }
            )
            with self._running_jobs_lock:
                if job.coalesce:
                    self._running_jobs.discard(job_name)

    def is_debounced(self, job: JobSpec) -> bool:
        """判断作业是否仍处于成功后的防抖时间窗口。"""

        if job.debounce_seconds <= 0:
            return False
        with self._last_success_lock:
            last_success = self._last_success_at.get(job.name)
        if last_success is None:
            return False
        return (_utc_now() - last_success).total_seconds() < job.debounce_seconds

    def _write(self, action):
        if self.writer is not None:
            return self.writer.call(action)
        return action()

    def _record(self, event: dict[str, object]) -> None:
        if self.trace_recorder is None:
            return
        try:
            self.trace_recorder.record(dict(event))
        except Exception:
            logger.exception("后台任务观测记录失败")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
