from __future__ import annotations

import threading
import time
from pathlib import Path

from flow_agent.background.jobs import JobSpec
from flow_agent.background.runtime import BackgroundRuntime, InMemoryJobRegistry
from flow_agent.background.store import SQLiteJobStore
from flow_agent.messaging.event_bus import Event, EventBus


def _runtime(
    tmp_path: Path,
    registry: InMemoryJobRegistry,
    *,
    event_bus: EventBus | None = None,
    max_async_queue: int = 8,
    max_async_workers: int = 2,
) -> BackgroundRuntime:
    return BackgroundRuntime(
        registry=registry,
        store=SQLiteJobStore(tmp_path / "background.db"),
        event_bus=event_bus,
        max_async_queue=max_async_queue,
        max_async_workers=max_async_workers,
    )


def test_event_trigger_submits_declared_plugin_job(tmp_path: Path):
    class RefreshEvent(Event):
        pass

    completed = threading.Event()
    registry = InMemoryJobRegistry()
    registry.register(
        JobSpec(
            name="plugin:refresh",
            func=completed.set,
            event_type=RefreshEvent,
        )
    )
    bus = EventBus()
    runtime = _runtime(tmp_path, registry, event_bus=bus)

    runtime.start()
    bus.publish(RefreshEvent(event_type="refresh"))

    assert completed.wait(timeout=1)
    runtime.stop()


def test_interval_trigger_runs_declared_job_after_start(tmp_path: Path):
    completed = threading.Event()
    registry = InMemoryJobRegistry()
    registry.register(
        JobSpec(
            name="plugin:interval",
            func=completed.set,
            interval_seconds=0.02,
        )
    )
    runtime = _runtime(tmp_path, registry)

    runtime.start()

    assert completed.wait(timeout=1)
    runtime.stop()


def test_coalesced_job_is_not_queued_twice_while_running(tmp_path: Path):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def work() -> None:
        calls.append("run")
        started.set()
        release.wait(timeout=1)

    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="plugin:coalesced", func=work))
    runtime = _runtime(tmp_path, registry, max_async_workers=1)

    runtime.start()
    runtime.run_job_async("plugin:coalesced")
    assert started.wait(timeout=1)
    runtime.run_job_async("plugin:coalesced")
    release.set()
    runtime.stop()

    assert calls == ["run"]


def test_worker_limit_keeps_second_job_queued_until_first_finishes(tmp_path: Path):
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    registry = InMemoryJobRegistry()
    registry.register(
        JobSpec(
            name="plugin:first",
            func=lambda: (first_started.set(), release_first.wait(timeout=1)),
        )
    )
    registry.register(JobSpec(name="plugin:second", func=second_started.set))
    runtime = _runtime(tmp_path, registry, max_async_workers=1)

    runtime.start()
    runtime.run_job_async("plugin:first")
    assert first_started.wait(timeout=1)
    runtime.run_job_async("plugin:second")
    time.sleep(0.05)
    assert not second_started.is_set()
    release_first.set()
    assert second_started.wait(timeout=1)
    runtime.stop()


def test_successful_job_is_debounced_until_window_expires(tmp_path: Path):
    calls = []
    completed = threading.Event()

    def work() -> None:
        calls.append("run")
        completed.set()

    registry = InMemoryJobRegistry()
    registry.register(
        JobSpec(
            name="plugin:debounced",
            func=work,
            debounce_seconds=0.2,
        )
    )
    runtime = _runtime(tmp_path, registry)

    runtime.start()
    assert runtime.run_job_async("plugin:debounced") is True
    assert completed.wait(timeout=1)
    assert runtime.run_job_async("plugin:debounced") is False
    time.sleep(0.25)
    assert runtime.run_job_async("plugin:debounced") is True
    runtime.stop()

    assert calls == ["run", "run"]
