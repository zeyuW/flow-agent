from __future__ import annotations

import threading
from pathlib import Path

from modules.jobs.domain.models import JobSpec
from modules.jobs.application.runtime import BackgroundRuntime, InMemoryJobRegistry
from modules.jobs.infra.store import SQLiteJobStore


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, event: dict[str, object]) -> None:
        self.events.append(event)


def _runtime(
    tmp_path: Path,
    registry: InMemoryJobRegistry,
    *,
    max_async_workers: int = 1,
    trace_recorder: object | None = None,
) -> BackgroundRuntime:
    return BackgroundRuntime(
        registry=registry,
        store=SQLiteJobStore(tmp_path / "background.db"),
        max_async_workers=max_async_workers,
        trace_recorder=trace_recorder,
    )


def test_permanent_job_error_does_not_consume_retry_budget(tmp_path: Path):
    attempts = []

    def invalid() -> None:
        attempts.append("attempt")
        raise ValueError("无效参数")

    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="plugin:invalid", func=invalid, max_retries=3))
    runtime = _runtime(tmp_path, registry)

    result = runtime.run_job("plugin:invalid")

    assert result.status == "failed"
    assert result.attempts == 1
    assert attempts == ["attempt"]
    runtime.stop()


def test_transient_job_error_retries_using_declared_policy(tmp_path: Path):
    attempts = []

    def flaky() -> str:
        attempts.append("attempt")
        if len(attempts) < 3:
            raise TimeoutError("临时超时")
        return "已恢复"

    registry = InMemoryJobRegistry()
    registry.register(
        JobSpec(
            name="plugin:flaky",
            func=flaky,
            max_retries=2,
            retry_delay_seconds=0,
            retry_backoff_factor=2,
        )
    )
    runtime = _runtime(tmp_path, registry)

    result = runtime.run_job("plugin:flaky")

    assert result.status == "succeeded"
    assert result.attempts == 3
    assert attempts == ["attempt", "attempt", "attempt"]
    runtime.stop()


def test_cancel_queued_job_does_not_cancel_running_job(tmp_path: Path):
    first_started = threading.Event()
    release_first = threading.Event()
    second_ran = threading.Event()

    def first() -> None:
        first_started.set()
        release_first.wait(timeout=1)

    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="plugin:first", func=first))
    registry.register(JobSpec(name="plugin:second", func=second_ran.set))
    runtime = _runtime(tmp_path, registry)
    runtime.start()
    runtime.run_job_async("plugin:first")
    assert first_started.wait(timeout=1)
    runtime.run_job_async("plugin:second")

    assert runtime.cancel_queued_job("plugin:first") == 0
    assert runtime.cancel_queued_job("plugin:second") == 1
    release_first.set()
    runtime.stop()

    assert not second_ran.is_set()
    restored = SQLiteJobStore(tmp_path / "background.db")
    assert [run.job_name for run in restored.list_runs()] == ["plugin:first"]
    restored.close()


def test_background_runtime_records_retry_lifecycle_without_result_content(
    tmp_path: Path,
):
    attempts = []
    recorder = _Recorder()
    completed = threading.Event()

    def flaky() -> str:
        attempts.append("attempt")
        if len(attempts) == 1:
            raise TimeoutError("临时超时")
        completed.set()
        return "不能写进观测事件的完整结果"

    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="plugin:observed", func=flaky, max_retries=1))
    runtime = _runtime(tmp_path, registry, trace_recorder=recorder)
    runtime.start()
    runtime.run_job_async("plugin:observed")

    assert completed.wait(timeout=1)
    runtime.stop()

    assert [event["type"] for event in recorder.events] == [
        "background_job_queued",
        "background_job_started",
        "background_job_retrying",
        "background_job_finished",
    ]
    assert recorder.events[-1]["status"] == "succeeded"
    assert all(
        "不能写进观测事件的完整结果" not in str(event)
        for event in recorder.events
    )


def test_trace_recorder_failure_does_not_change_job_result(tmp_path: Path):
    class _FailingRecorder:
        def record(self, event: dict[str, object]) -> None:
            del event
            raise RuntimeError("观测存储不可用")

    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="plugin:ok", func=lambda: "完成"))
    runtime = _runtime(tmp_path, registry, trace_recorder=_FailingRecorder())

    result = runtime.run_job("plugin:ok")

    assert result.status == "succeeded"
    runtime.stop()
