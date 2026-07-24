from pathlib import Path
import threading

from flow_agent.background.jobs import JobSpec
from flow_agent.background.runtime import BackgroundRuntime, InMemoryJobRegistry
from flow_agent.background.store import SQLiteJobStore
from flow_agent.background.tools import (
    ListBackgroundJobsTool,
    ListBackgroundRunsTool,
    RunBackgroundJobTool,
)


def test_background_job_state_and_history_survive_restart(tmp_path: Path):
    path = tmp_path / "background.db"
    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="demo", func=lambda: "完成"))
    store = SQLiteJobStore(path)
    runtime = BackgroundRuntime(registry=registry, store=store)

    run = runtime.run_job("demo")

    assert run.status == "succeeded"
    assert run.result == "完成"
    runtime.stop()

    restored = SQLiteJobStore(path)
    runs = restored.list_runs()
    assert len(runs) == 1
    assert runs[0].run_id == run.run_id
    assert runs[0].status == "succeeded"
    assert runs[0].result == "完成"
    restored.close()


def test_background_tools_expose_registered_jobs_and_persisted_runs(tmp_path: Path):
    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="demo", func=lambda: "完成"))
    store = SQLiteJobStore(tmp_path / "background.db")
    runtime = BackgroundRuntime(registry=registry, store=store)
    runtime.run_job("demo")

    jobs = ListBackgroundJobsTool(runtime).run({})
    runs = ListBackgroundRunsTool(runtime).run({"limit": 5})

    assert '"demo"' in jobs.content
    assert '"status": "succeeded"' in runs.content
    runtime.stop()


def test_background_runtime_persists_real_retry_count(tmp_path: Path):
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("暂时失败")
        return "恢复"

    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="flaky", func=flaky, max_retries=2))
    store = SQLiteJobStore(tmp_path / "background.db")
    runtime = BackgroundRuntime(registry=registry, store=store)

    run = runtime.run_job("flaky")

    assert run.status == "succeeded"
    assert run.attempts == 3
    runtime.stop()


def test_background_tool_suggests_name_for_typo(tmp_path: Path):
    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="resume_probe:collect", func=lambda: None))
    runtime = BackgroundRuntime(
        registry=registry,
        store=SQLiteJobStore(tmp_path / "background.db"),
    )

    result = RunBackgroundJobTool(runtime).run({
        "job_name": "resume_prob：collet",
    })

    assert result.ok is False
    assert "resume_probe:collect" in result.content
    runtime.stop()


def test_different_background_jobs_can_run_with_bounded_parallelism(tmp_path: Path):
    """不同任务不能因全局运行锁而互相拒绝。"""

    started = []
    both_started = threading.Event()
    release = threading.Event()
    finished = []

    def work(name):
        started.append(name)
        if len(started) == 2:
            both_started.set()
        release.wait(timeout=1)
        finished.append(name)

    registry = InMemoryJobRegistry()
    registry.register(JobSpec(name="first", func=lambda: work("first")))
    registry.register(JobSpec(name="second", func=lambda: work("second")))
    runtime = BackgroundRuntime(
        registry=registry,
        store=SQLiteJobStore(tmp_path / "background.db"),
        max_async_queue=2,
    )

    runtime.run_job_async("first")
    runtime.run_job_async("second")
    assert both_started.wait(timeout=1)
    release.set()
    runtime.stop()

    assert sorted(finished) == ["first", "second"]
