from pathlib import Path
import threading

from application.automation.domain.models import JobSpec
from application.automation.app.runtime import AutomationRuntime, AutomationRegistry
from application.automation.infra.store import SQLiteJobStore
from infra.persistence import SQLiteDatabase
from application.capabilities.tools.automation import (
    ListAutomationJobsTool,
    ListAutomationRunsTool,
    RunAutomationJobTool,
)


def test_background_job_state_and_history_survive_restart(tmp_path: Path):
    path = tmp_path / "background.db"
    registry = AutomationRegistry()
    registry.register(JobSpec(name="demo", func=lambda: "完成"))
    store = SQLiteJobStore(path)
    runtime = AutomationRuntime(registry=registry, store=store)

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


def test_background_store_uses_shared_sqlite_infrastructure(tmp_path: Path):
    store = SQLiteJobStore(tmp_path / "background.db")

    assert isinstance(store.database, SQLiteDatabase)

    store.close()


def test_background_tools_expose_registered_jobs_and_persisted_runs(tmp_path: Path):
    registry = AutomationRegistry()
    registry.register(JobSpec(name="demo", func=lambda: "完成"))
    store = SQLiteJobStore(tmp_path / "background.db")
    runtime = AutomationRuntime(registry=registry, store=store)
    runtime.run_job("demo")

    jobs = ListAutomationJobsTool(runtime).run({})
    runs = ListAutomationRunsTool(runtime).run({"limit": 5})

    assert '"demo"' in jobs.content
    assert '"status": "succeeded"' in runs.content
    runtime.stop()


def test_automation_runtime_persists_real_retry_count(tmp_path: Path):
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("暂时失败")
        return "恢复"

    registry = AutomationRegistry()
    registry.register(JobSpec(name="flaky", func=flaky, max_retries=2))
    store = SQLiteJobStore(tmp_path / "background.db")
    runtime = AutomationRuntime(registry=registry, store=store)

    run = runtime.run_job("flaky")

    assert run.status == "succeeded"
    assert run.attempts == 3
    runtime.stop()


def test_background_tool_suggests_name_for_typo(tmp_path: Path):
    registry = AutomationRegistry()
    registry.register(JobSpec(name="resume_probe:collect", func=lambda: None))
    runtime = AutomationRuntime(
        registry=registry,
        store=SQLiteJobStore(tmp_path / "background.db"),
    )

    result = RunAutomationJobTool(runtime).run({
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

    registry = AutomationRegistry()
    registry.register(JobSpec(name="first", func=lambda: work("first")))
    registry.register(JobSpec(name="second", func=lambda: work("second")))
    runtime = AutomationRuntime(
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
