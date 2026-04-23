import time
from pathlib import Path

from flow_agent.background.jobs import JobSpec
from flow_agent.background.runtime import BackgroundRuntime, InMemoryJobRegistry
from flow_agent.background.store import InMemoryJobStore
from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.subagent.manager import SubagentManager


def test_background_runtime_records_job_events():
    dashboard = InMemoryDashboardStore()
    registry = InMemoryJobRegistry()
    store = InMemoryJobStore()
    runtime = BackgroundRuntime(registry=registry, store=store, dashboard=dashboard)
    ran = {"n": 0}

    def job() -> None:
        ran["n"] += 1

    registry.register(JobSpec(name="j1", func=job, max_retries=0))
    run = runtime.run_job("j1")
    assert run.ok is True
    snap = dashboard.snapshot()
    assert any(e.get("type") == "job_start" for e in snap.jobs)
    assert any(e.get("type") == "job_end" for e in snap.jobs)


def test_subagent_manager_persists_and_records(tmp_path: Path):
    dashboard = InMemoryDashboardStore()
    mgr = SubagentManager(tasks_path=tmp_path / "tasks.jsonl", dashboard=dashboard)
    task = mgr.create_task("echo", {"text": "hi"})

    def executor(t):
        return {"echo": t.payload["text"]}

    mgr.run_task(task, executor=executor)
    time.sleep(0.05)
    # ensure events recorded
    snap = dashboard.snapshot()
    assert any(e.get("type") == "subagent_task_created" for e in snap.subagents)
    assert any(e.get("type") == "subagent_task_finished" for e in snap.subagents)
    # ensure persisted
    lines = (tmp_path / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(task.task_id in line for line in lines)

