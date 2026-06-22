"""Subagent runtime factory."""

from dataclasses import dataclass
from pathlib import Path

from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.subagent.manager import SubagentManager


@dataclass(slots=True)
class SubagentRuntime:
    """Container for subagent manager."""
    manager: SubagentManager


def create_subagent_runtime(
    data_dir: Path,
    dashboard: InMemoryDashboardStore | None = None,
    *,
    tasks_file: str | None = None,
    max_concurrency: int = 2,
    message_bus=None,
    llm_client=None,
) -> SubagentRuntime:
    task_path = Path(tasks_file) if tasks_file else (data_dir / "subagent_tasks.jsonl")
    manager = SubagentManager(
        tasks_path=task_path,
        dashboard=dashboard,
        message_bus=message_bus,
        llm_client=llm_client,
    )
    manager.max_concurrency = max_concurrency
    return SubagentRuntime(manager=manager)
