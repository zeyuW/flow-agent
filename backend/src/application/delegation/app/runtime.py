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
    max_total_per_run: int = 6,
    max_turns: int = 10,
    timeout_seconds: float = 300.0,
    message_bus=None,
    llm_client=None,
    event_bus=None,
) -> SubagentRuntime:
    task_path = Path(tasks_file) if tasks_file else (data_dir / "subagent_tasks.jsonl")
    manager = SubagentManager(
        task_store=JsonlTaskStore(task_path),
        message_bus=message_bus,
        llm_client=llm_client,
        event_bus=event_bus,
    )
    manager.max_concurrency = max_concurrency
    manager.max_total_subagents = max_total_per_run
    manager.default_max_turns = max_turns
    manager.default_timeout_seconds = timeout_seconds
    return SubagentRuntime(manager=manager)
