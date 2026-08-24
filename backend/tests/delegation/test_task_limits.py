from application.delegation.app.manager import SubagentManager
from application.delegation.app.models import SubagentResult
from application.delegation.infra.store import JsonlTaskStore


def test_manager_rejects_task_when_run_total_limit_is_reached(tmp_path):
    manager = SubagentManager(task_store=JsonlTaskStore(tmp_path / "tasks.jsonl"))
    manager.max_total_subagents = 1
    manager._task_counts["run-1"] = 1

    decision = manager._reserve_task("run-1")

    assert decision.allowed is False
    assert decision.reason == "subagent_total_limit"


def test_manager_records_and_releases_active_task_slot(tmp_path):
    manager = SubagentManager(task_store=JsonlTaskStore(tmp_path / "tasks.jsonl"))

    decision = manager._reserve_task("run-1")
    assert decision.allowed is True
    assert manager._active_task_count == 1

    manager._release_task("run-1")

    assert manager._active_task_count == 0


def test_manager_persists_task_lifecycle(tmp_path):
    manager = SubagentManager(task_store=JsonlTaskStore(tmp_path / "tasks.jsonl"))

    class Executor:
        async def execute(self, **kwargs):
            return SubagentResult(
                task_id=kwargs["task_id"],
                status="completed",
                summary="完成",
                steps=1,
            )

    manager._executor = Executor()
    try:
        result = manager.run_task_threadsafe(
            task_id="task-1",
            description="执行",
            run_id="run-1",
        )
    finally:
        manager.shutdown()

    assert result.status == "completed"
    phases = [
        row["phase"]
        for row in manager.list_recent_tasks()
        if row.get("type") == "spawn_trace"
    ]
    assert phases == ["started", "completed"]
