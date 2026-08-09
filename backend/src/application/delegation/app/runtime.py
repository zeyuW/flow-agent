"""Subagent runtime factory."""

from dataclasses import dataclass
from pathlib import Path

from application.delegation.app.manager import SubagentManager
from application.delegation.infra.store import JsonlTaskStore


@dataclass(slots=True)
class SubagentRuntime:
    """Container for subagent manager."""
    manager: SubagentManager


def create_subagent_runtime(
    data_dir: Path,
    *,
    tasks_file: str | None = None,
    max_concurrency: int = 2,
    message_bus=None,
    llm_client=None,
) -> SubagentRuntime:
    task_path = Path(tasks_file) if tasks_file else (data_dir / "subagent_tasks.jsonl")
    manager = SubagentManager(
        task_store=JsonlTaskStore(task_path),
        message_bus=message_bus,
        llm_client=llm_client,
    )
    manager.max_concurrency = max_concurrency
    return SubagentRuntime(manager=manager)
